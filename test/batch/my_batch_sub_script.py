# Author Tiziano Bevilacqua (05/13/2022) 
# Script to submit nAODomisation jobs to slurm, tested on PSI tier3 

from importlib.metadata import metadata
import re, os, sys, glob, time, logging, multiprocessing, socket, subprocess, shlex, getpass, math, shutil
from optparse import OptionParser
import json
from importlib import resources

# ---------------------- A few helping functions  ----------------------

def colored_text(txt, keys=[]):
    _tmp_out = ''
    for _i_tmp in keys:
        _tmp_out += '\033['+_i_tmp+'m'
    _tmp_out += txt
    if len(keys) > 0: _tmp_out += '\033[0m'

    return _tmp_out

color_dict = {
    "cyan": '\033[96m',
    "green": '\033[92m',
    "red": '\033[91m',
    "yellow": '\33[33m',
    "blue": '\33[34m',
    "white": '\033[37m',
    "bold": '\033[01m',
    "end": '\033[0m'
    
}

def KILL(log):
    raise RuntimeError('\n '+colored_text('@@@ FATAL', ['1','91'])+' -- '+log+'\n')

def WARNING(log):
    print ('\n '+colored_text('@@@ WARNING', ['1','93'])+' -- '+log+'\n')

def MKDIRP(dirpath, verbose=False, dry_run=False):
    if verbose: print ('\033[1m'+'>'+'\033[0m'+' os.mkdirs("'+dirpath+'")')
    if dry_run: return
    try:
      os.makedirs(dirpath)
    except OSError:
      if not os.path.isdir(dirpath):
        raise
    return

def EXE(cmd, suspend=True, verbose=False, dry_run=False):
    if verbose: print ('\033[1m'+'>'+'\033[0m'+' '+cmd)
    if dry_run: return

    _exitcode = os.system(cmd)
    _exitcode = min(255, _exitcode)

    if _exitcode and suspend:
       raise RuntimeError(_exitcode)

    return _exitcode

#----------------------------------------------------------------------------------------------------------#
#----------------------------------------------------------------------------------------------------------#
#- USAGE: -------------------------------------------------------------------------------------------------#
#- python my_batch_sub_script.py --input [config json file, example in the configs dir] --create ----------#
#- python my_batch_sub_script.py --input [config json file, example in the configs dir] --status ----------#
#- python my_batch_sub_script.py --input [config json file, example in the configs dir] --submit ----------#
#- python my_batch_sub_script.py --input [config json file, example in the configs dir] --resubmit --------#
#- python my_batch_sub_script.py --input [config json file, example in the configs dir] --missing ---------#
#- python my_batch_sub_script.py --input [config json file, example in the configs dir] --hadd ------------#
#----------------------------------------------------------------------------------------------------------#
#----------------------------------------------------------------------------------------------------------#

# Read options from command line
usage = "Usage: python %prog filelists [options]"
parser = OptionParser(usage=usage)
parser.add_option("--slurm_file",  dest="job_template",type="string",       default="slurm_template.sh", help="Slurm job template")
parser.add_option("--input",       dest="input",       type="string",       default="",    help="input filelist")
parser.add_option("--create",      dest="create",      action="store_true", default=False, help="create taskdir under PHM_PHASE1_out/ and prepare submission scripts, it divide the input filelist (provided with --input) according to the number of file for each job (specified with --nfile)")
parser.add_option("--submit",      dest="submit",      action="store_true", default=False, help="submit jobs from task")
parser.add_option("--resubmit",    dest="resubmit",    action="store_true", default=False, help="prepare resubmit script with missing jobs")
parser.add_option("--status",      dest="status",      action="store_true", default=False, help="check status of submitted jobs (R, PD, Completed")
parser.add_option("--missing",     dest="missing",     action="store_true", default=False, help="look for missing jobs")
parser.add_option("--hadd",        dest="hadd",        action="store_true", default=False, help="Submit hadding job")
parser.add_option("--step_two",    dest="step_2",      action="store_true", default=False, help="Option to merge merged outputs")
parser.add_option("--per_file",    dest="per_file",    action="store_true", default=False, help="Create one job per input file (instead of one job per run)")
parser.add_option("--queue",       dest="queue",       type="string",       default="standard", help="slurm queue to submit jobs to, default: standard, if this needs to be changed one should also have a look at the --time option")
parser.add_option("--time",        dest="time",        type="string",       default="12:00:00", help="slurm job time limit, default: 12:00:00, make sure not to exceed time limit for each partition (for limits ref to https://wiki.chipp.ch/twiki/bin/view/CmsTier3/SlurmUsage) ")
parser.add_option("--debug",       dest="debug",       action="store_true", default=False, help="Debug verbosity and skip removing of some intermediate files")
(opt,args) = parser.parse_args()

# --------------------- Proxy check ----------------------
if opt.input == "":
    KILL("no config json specified")
else:
    with open(opt.input) as f:
        metadata = json.load(f)

os.system("voms-proxy-info --timeleft > proxy.txt")
with open('proxy.txt') as proxyfile:
    lines = proxyfile.readlines()
    if len(lines)==1:
        if not "Proxy not found" in lines[0]:
            timeleft = int(lines[0])
os.remove('proxy.txt')
if timeleft<1000: #172800:
    print ("-"*80)
    print (color_dict["red"]+"New proxy needed"+color_dict["end"])
    print ("suggest to use: voms-proxy-init -voms cms -valid 168:00")
    print ("-"*80)
    raise RuntimeError("PROXY ERROR")
else:
    print ("-"*80)
    print (color_dict["green"]+"Current proxy is long enough"+color_dict["end"])
    print ("-"*80)

# ----------------------  Settings -----------------------
# Some further (usually) fixed settings, should edit them in this file

# Output directories/files
SUBTIME = time.strftime("%Y_%m_%d_%Hh%Mm%S", time.localtime())
if metadata["outdir"] == "":
    KILL("no output directory specified")

# Working directory, during running we cd here and back
OUT_PATH = metadata["outdir"]
EXEC_PATH = os.getcwd()
EXEC_PATH = EXEC_PATH+"/"+metadata["taskname"]

if opt.create:
    # Check input filelist
    if opt.input == "": KILL("no configuration provided provided (--input configs/<your_config>.json)")

    # Create Task dir and copy input filelist and slurm template
    opt.input = os.path.abspath(opt.input)
    metadata["job_template"] = os.path.abspath(metadata["job_template"])
    MKDIRP(EXEC_PATH+"/filelists")
    if len(os.listdir(EXEC_PATH+"/filelists")) != 0:
        os.system("rm "+EXEC_PATH+"/filelists/*")
    os.chdir(EXEC_PATH) 
    EXEC_PATH = os.getcwd()
    era = metadata["era"]
    cert_filename = ""
    if metadata["cert"] != "":
        cert_filename = metadata["cert"]
        with open(metadata["cert"]) as c:
            cerified_runs = json.load(c)
    else:
        raise Exception(
            "You haven't provided a certification json, this is not supported anymore"
        )

    runs = metadata["runs"] if isinstance(metadata["runs"], list) else cerified_runs
    print("Processing runs: ", runs)
    for i, run in enumerate(runs):
        run = str(run)
        ash = int((100.0/len(runs)*i) // 1)
        space = int((100.0/len(runs)*(len(runs)-(i+1)) // 1))-2
        print ("preparing job scripts "+color_dict["cyan"]+"|"+"#"*ash+" "*space+"|"+color_dict["end"], end="\r")
        # This is a workaround to include bot Muon0 and Muon1 file in the same Ntuple, so that we still get just one file per run
        if isinstance(metadata["sample"], list):
            for samp in metadata["sample"]:
                os.system("dasgoclient -query=\"file dataset="+samp+" run="+run+"\" >> filelists/input_run"+run+".txt")
        else:
            os.system("dasgoclient -query=\"file dataset="+metadata["sample"]+" run="+run+"\" > filelists/input_run"+run+".txt")
        if os.stat("filelists/input_run"+run+".txt").st_size == 0:
            if isinstance(metadata["backup_sample"], list):
                for samp in metadata["backup_sample"]:
                    if isinstance(samp, list):
                        for subsamp in samp:
                            os.system("dasgoclient -query=\"file dataset="+subsamp+" run="+run+"\" >> filelists/input_run"+run+".txt")
                    else:
                        os.system("dasgoclient -query=\"file dataset="+samp+" run="+run+"\" >> filelists/input_run"+run+".txt")
            else:
                os.system("dasgoclient -query=\"file dataset="+metadata["backup_sample"]+" run="+run+"\" > filelists/input_run"+run+".txt")

    if opt.per_file:
        split_lists = []
        for run in runs:
            run = str(run)
            run_filelist = "filelists/input_run"+run+".txt"
            if not os.path.isfile(run_filelist):
                continue
            with open(run_filelist) as file_list:
                files = [line.strip() for line in file_list.readlines() if line.strip()]
            for file_idx, file_name in enumerate(files, start=1):
                split_name = "filelists/input_run"+run+"_file"+str(file_idx).zfill(4)+".txt"
                with open(split_name, "w") as split_file:
                    split_file.write(file_name+"\n")
                split_lists.append(split_name)
            os.remove(run_filelist)

        if len(split_lists) == 0:
            KILL("no input files found while using --per_file")

    os.system("cp "+metadata["job_template"]+" "+EXEC_PATH+"/slurm_jobscript.sh")

    if opt.queue != "standard":
        os.system("sed \"s;\#SBATCH --partition=standard;\#SBATCH --partition="+opt.queue+";g\" slurm_jobscript.sh > tmp")
        os.system("mv tmp slurm_jobscript.sh")
    if opt.time != "12:00:00":
        os.system("sed -E \"s;\#SBATCH --time=([0-9]+):00:00;\#SBATCH --time="+opt.time+";g\" "+EXEC_PATH+"/slurm_jobscript.sh > tmp")
        os.system("mv tmp slurm_jobscript.sh")
    os.system("cp "+cert_filename+" "+EXEC_PATH+"/")

    if opt.per_file:
        job_input_files = sorted([os.path.basename(path) for path in glob.glob("filelists/input_run*_file*.txt")])
    else:
        job_input_files = sorted([os.path.basename(path) for path in glob.glob("filelists/input_run*.txt")])

    if len(job_input_files) == 0:
        KILL("no input filelists were created")

    with open("filelists/job_list.txt", "w") as job_list_file:
        for file_name in job_input_files:
            job_list_file.write(file_name+"\n")

    n_jobs = len(job_input_files)

    # Summary file
    os.system("echo \"NTuple conversion process for "+metadata["taskname"]+" summary\" > "+EXEC_PATH+"/summary.txt")
    os.system("echo \"\" >> "+EXEC_PATH+"/summary.txt")
    os.system("echo \"Task name: "+metadata["taskname"]+"\" >> "+EXEC_PATH+"/summary.txt")
    os.system("echo \"Output dir: "+metadata["outdir"]+"\" >> "+EXEC_PATH+"/summary.txt")
    os.system("echo \"Input filelists in : filelists/input*.txt\" >> "+EXEC_PATH+"/summary.txt")
    os.system("echo \"Slurm jobs template: slurm_jobscript.sh\" >> "+EXEC_PATH+"/summary.txt")
    os.system("echo \"Number of jobs: "+str(n_jobs)+"\" >> "+EXEC_PATH+"/summary.txt")
    
    print()
    print ("-"*80)
    print ("number of jobs: ", n_jobs)
    
    # Prepare submission script with "sbatch [job name] [out-log] [out-err] slurm_jobscript.sh [GoodLumi.json path] [job_label] [input_files_list] [output dir] [other self explanatory options for cmsDriver]  
    print ("")
    if cert_filename == "": cert_filename = "DUMMY"
    print ("Job Script file: "+color_dict["blue"]+metadata["job_template"]+color_dict["end"])
    os.system("cat -n filelists/job_list.txt | awk '{ printf \"%.4d %s\\n\", $1, $2 }' | awk '{ print \"sbatch --job-name="+metadata["taskname"]+"_\"$1\" -o /work/%u/test/.slurm/%x_%A_\"$1\".out -e /work/%u/test/.slurm/%x_%A_\"$1\".err slurm_jobscript.sh "+metadata["taskname"]+"_\"$1\" "+metadata["cmssw"]+" "+metadata["outdir"]+"/"+metadata["taskname"]+"  \"$1\" "+metadata["datatier"]+" "+metadata["conditions"]+" "+metadata["cmsRun_script"]+" "+cert_filename+" "+EXEC_PATH+"/filelists/\"$2\"\"}' > alljobs.sh")
    os.system("head -1 alljobs.sh | sed \"s;0001;test;g;\" > test.sh")

    print ("Jobs prepared at:", color_dict["blue"]+os.getcwd()+color_dict["end"], "as: "+color_dict["blue"]+"alljobs.sh"+color_dict["end"]) 
    print ("or test 1 job with: test.sh")
    print ("-"*80)

    print ("-"*80)

    # Option to submit jobs right away
    answ = input(color_dict["green"]+"Do you want to directly submit the jobs to slurm (all jobs or 1 test job)? (y/n/test) \n"+color_dict["end"])
    if str(answ) == "y":
        os.system("wc -l alljobs.sh | awk '{print \"submitting \"$1\" jobs from \"$2\" ...\"}'")
        EXE("sh alljobs.sh")   
    elif str(answ) == "test":
        os.system("wc -l test.sh | awk '{print \"submitting \"$1\" jobs from \"$2\" ...\"}'")
        EXE("sh test.sh") 
    print ("-"*80)

# Same as before, ask for submission of jobs
elif opt.submit:
    os.chdir(EXEC_PATH) 
    EXEC_PATH = os.getcwd()
    print ("-"*80)
    answ = input(color_dict["green"]+"Do you want to directly submit the jobs to slurm (all jobs or 1 test job)? (y/n/test) \n"+color_dict["end"])
    if str(answ) == "y":
        os.system("wc -l alljobs.sh | awk '{print \"submitting \"$1\" jobs from \"$2\" ...\"}'")
        EXE("sh alljobs.sh")   
    elif str(answ) == "test":
        os.system("wc -l test.sh | awk '{print \"submitting \"$1\" jobs from \"$2\" ...\"}'")
        EXE("sh test.sh") 
    print ("-"*80)
    
# Check the status of submitted jobs, it recover job info from summary file in the task directory 
# and query squeue for pending and running jobs. Then check the output dir to look for completed jobs.
elif opt.status:
    print ("-"*80)
    with open(EXEC_PATH+"/summary.txt") as fl:
        lines = fl.readlines()
        for line in lines:
            fields = re.split(": |\n", line)
            if fields[0] == "Number of jobs":
                njobs = int(fields[1])
            elif fields[0] == "Task name":
                TASKNAME = fields[1]
            elif fields[0] == "Output dir":
                OUT_PATH = fields[1]
                
    os.system("( squeue -n `cat "+EXEC_PATH+"/alljobs.sh | awk '{print $2}' | sed 's;--job-name=;;g;' | sed ':label1 ; N ; $! b label1;s;\\n;,;g'` > taskjobs ) > /dev/null")
    os.system("grep PD taskjobs > Pending")
    os.system("grep \" R \" taskjobs > Running")
    os.system("( ls "+OUT_PATH+"/"+TASKNAME+" | grep .root > Completed ) >  /dev/null")
    os.system("sort -u Completed > Comp")
    os.system("mv Comp Completed")
    os.system("ls -l "+OUT_PATH+"/"+TASKNAME+"/logs | grep -v test | grep .out > Done")
    os.system("echo "+color_dict["bold"]+"\"Status of Task "+TASKNAME+": ("+str(njobs)+" Jobs)\""+color_dict["end"])
    os.system("echo \"Jobs - Pending                : `wc -l Pending | awk '{ print $1}'`\"")
    os.system("echo \"     - Running                : `wc -l Running | awk '{ print $1}'`\"")
    os.system("echo \"     - Done (with STDOUT)     : `wc -l Done | awk '{ print $1}'`\"")
    os.system("echo \"------------------------------------\"")
    os.system("echo \"     - "+color_dict["green"]+"Completed (has output) : `wc -l Completed | awk '{ print $1}'`\""+color_dict["end"])
    os.system("rm taskjobs Pending Running Completed Done")
    print ("-"*80)
    
# Look for finished jobs and then prints number of jobs that are not in the output dir
elif opt.missing:
    print ("-"*80)
    with open(EXEC_PATH+"/summary.txt") as fl:
        lines = fl.readlines()
        for line in lines:
            fields = re.split(": |\n", line)
            if fields[0] == "Number of jobs":
                njobs = int(fields[1])
            elif fields[0] == "Task name":
                TASKNAME = fields[1]
            elif fields[0] == "Output dir":
                OUT_PATH = fields[1]

    os.system("ls "+OUT_PATH+"/"+TASKNAME+" | grep .root >> output")
    os.system("cat output | sort -u | sed 's;_; ;g;s;\.; ;g' | awk '{ printf \"%d\\n\", $(NF-1) }' > jobnums")
    os.system("seq 1 "+str(njobs)+" > Seq")
    os.system("diff Seq jobnums | grep \"<\" | awk '{ printf \"%d,\", $2 }' | sed 's;,$;\\n;'")
    os.system("rm Seq jobnums output")
    print ("-"*80)

# same as missing option but also prepare a resubmission script for such jobs
elif opt.resubmit:
    print ("-"*80)
    with open(EXEC_PATH+"/summary.txt") as fl:
        lines = fl.readlines()
        for line in lines:
            fields = re.split(": |\n", line)
            if fields[0] == "Number of jobs":
                njobs = int(fields[1])
            elif fields[0] == "Task name":
                TASKNAME = fields[1]
            elif fields[0] == "Output dir":
                OUT_PATH = fields[1]
    os.chdir(EXEC_PATH) 
    EXEC_PATH = os.getcwd()

    os.system("ls "+OUT_PATH+"/"+TASKNAME+" | grep .root >> output")
    os.system("cat output | sort -u | sed 's;_; ;g;s;\.; ;g' | awk '{ printf \"%d\\n\", $(NF-1) }' > jobnums")
    os.system("seq 1 "+str(njobs)+" > Seq")
    os.system("diff Seq jobnums | grep \"<\" | awk '{ printf \"%.4d,\", $2 }' | sed 's;,$;\\n;' > resubmit ")
    if os.path.exists(EXEC_PATH+"/resubmit.sh"): os.system("rm "+EXEC_PATH+"/resubmit.sh")
    with open("resubmit") as fl:
        files = fl.readlines()
        if len(files) > 0:
            files = re.split(',|\n',files[0])
        for i,job in enumerate(files):
            if job == '': break
            idx = (int((i/(float(len(files))/100)) // 1) if (len(files) > 2) else 100)
            print ("preparing resubmission jobs list "+color_dict["cyan"]+"|"+"#"*idx+" "*(100-idx)+"|"+color_dict["end"], end="\r")
            os.system("grep "+TASKNAME+"_"+job+" "+EXEC_PATH+"/alljobs.sh >> "+EXEC_PATH+"/resubmit.sh")
    os.system("rm Seq jobnums output resubmit")

    # change job queue if needed
    if opt.queue != "standard":
        os.system("sed \"s;\#SBATCH --partition=standard;\#SBATCH --partition="+opt.queue+";g\" "+EXEC_PATH+"/slurm_jobscript.sh > tmp")
        os.system("mv tmp "+EXEC_PATH+"/slurm_jobscript.sh")
    if opt.time != "12:00:00":
        os.system("sed -E \"s;\#SBATCH --time=([0-9]+):00:00;\#SBATCH --time="+opt.time+";g\" "+EXEC_PATH+"/slurm_jobscript.sh > tmp")
        os.system("mv tmp "+EXEC_PATH+"/slurm_jobscript.sh")

    if len(files) > 0:
        print("\nDone: "+color_dict["blue"]+"resubmit.sh"+color_dict["end"]+" file created at "+color_dict["blue"]+EXEC_PATH+"/resubmit.sh"+color_dict["end"])
    else:    
        print("No jobs to resubmit")
    print ("-"*80) 

# Submit hadd job for files in the output directory !!! TO BE FIXED, old version, in principle should not be needed !!! FIXME !!!
elif opt.hadd:
    print ("-"*80)
    with open(EXEC_PATH+"/summary.txt") as fl:
        lines = fl.readlines()
        for line in lines:
            fields = re.split(": |\n", line)
            if fields[0] == "Number of jobs":
                njobs = int(fields[1])
            elif fields[0] == "Task name":
                TASKNAME = fields[1]
            elif fields[0] == "Output dir":
                OUT_PATH = fields[1]
            elif fields[0] == "Program to run":
                PROG = fields[1]

    os.chdir(EXEC_PATH) 
    EXEC_PATH = os.getcwd()
    nfile_pj = 10
    if opt.step_2:
        merged_dir = "/merged"
        merg = "merged | grep "  
        os.system("rm filelists/merging* ")
        njobs = int(njobs/10)
        nfile_pj = 10
    else:
        merg = ""  
        merged_dir = ""   
    if njobs > 10:
        os.system("ls -l "+OUT_PATH+"/"+TASKNAME+merged_dir+" | grep "+merg+".root | awk '{ print \"/\" $9}' | sed \"s:^:"+OUT_PATH+"/"+TASKNAME+merged_dir+":\" | sed \"s:/pnfs/psi.ch/cms/trivcat/:root\://cms-xrd-global.cern.ch//:\" > filelists/tmp")
    else:
        os.system("ls -l "+OUT_PATH+"/"+TASKNAME+merged_dir+" | grep "+merg+".root | awk '{ print \"/\" $9}' | sed \"s:^:"+OUT_PATH+"/"+TASKNAME+merged_dir+":\" | sed \"s:/pnfs/psi.ch/cms/trivcat/:root\://cms-xrd-global.cern.ch//:\" > filelists/tmp")
    for i in range(int(njobs/nfile_pj) if int(njobs/nfile_pj) >= 1 else 1):
        os.system("tail -n "+str(nfile_pj)+" filelists/tmp > filelists/merging_"+str(i))
        os.system("head -n -"+str(nfile_pj)+" filelists/tmp > tmptmp")
        os.system("mv tmptmp filelists/tmp")
    os.system("rm filelists/tmp")

    os.system("ls -l filelists | grep merging | grep -v merging_job_list.txt | awk '{ print $NF }' > filelists/merging_job_list.txt")
                                           #$1              $2      $3      $4     $5       $6
    #sbatch jobname .out .log slurm.sh jobname(redundant) job_ID filelist outdir program --hadd
    os.system("cat -n filelists/merging_job_list.txt | awk '{ printf \"%.4d %s\\n\", $1, $2 }' | awk `{ print \"sbatch --job-name="+TASKNAME+"_MERGING_\"$1\" -o /work/%u/test/.slurm/%x_%A_\"$1\".out -e /work/%u/test/.slurm/%x_%A_\"$1\".err slurm_jobscript.sh "+TASKNAME+"_JOBMERGING\"$1\" \"$1\" "+EXEC_PATH+"/filelists/\"$2\" "+OUT_PATH+"/"+TASKNAME+merged_dir+" "+PROG+" --hadd\"}` | sed \"s;*;\';g\" > merging_alljobs.sh")
    os.system("head -1 merging_alljobs.sh | sed \"s;0001;test;g;\" > merging_test.sh")
    
    answ = input(color_dict["green"]+"Do you want to directly submit the jobs to slurm (all jobs or 1 test job)? (y/n/test) \n"+color_dict["end"])
    if str(answ) == "y":
        os.system("wc -l merging_alljobs.sh | awk '{print \"submitting \"$1\" jobs from \"$2\" ...\"}'")
        EXE("sh merging_alljobs.sh")   
        os.system("wc -l merging_alljobs.sh | awk '{print \"submitted \"$1\" jobs from \"$2\" ...\"}'")
    elif str(answ) == "test":
        os.system("wc -l merging_test.sh | awk '{print \"submitting \"$1\" jobs from \"$2\" ...\"}'")
        EXE("sh merging_test.sh") 

    if not opt.debug:
        os.system("rm filelists/merging_job_list.txt")
        #os.system("rm filelists/merging*")

    print ("-"*80)
