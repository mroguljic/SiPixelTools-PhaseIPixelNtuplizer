#!/usr/bin/env python3
"""Slurm submission for the pixel hit-efficiency-from-RAW measurement.

One job per run. Each job reconstructs ZeroBias RAW with
reconstruction_trackingOnly, restricted to the certified (golden) lumisections,
and writes the slim hit-efficiency tree.

Deliberately separate from my_batch_sub_script.py: that one drives the
ntuplizer and couples to its cfg naming and dataTier argument. This workflow
needs an era recipe instead, and wants shuffled input files, so it is simpler
to keep the two apart than to generalise one script over both.

Why shuffled: input files come back from DAS in lumisection order, so taking
the first N events of a run would sample the start of every fill. Pixel
inactivity varies within a run -- FEDerror25 comes and goes per lumisection,
which is the effect being measured -- so the file list is shuffled (with a
fixed seed, per run, so the selection is reproducible) before truncation.

Usage
-----
  ./submit_hitEffFromRaw.py --input hitEff_Run2026D.json --create
  ./submit_hitEffFromRaw.py --input hitEff_Run2026D.json --submit
  ./submit_hitEffFromRaw.py --input hitEff_Run2026D.json --status

Config JSON fields
------------------
  taskname     directory created here to hold the task
  sample       DAS dataset, e.g. /ZeroBias/Run2026D-v1/RAW
  runs         explicit list of run numbers to process
  maxevents    events per run (per job)
  recipe       2025_AtoE | 2025_F | 2025_G | 2026_pre402532 | 2026
  conditions   global tag
  cert         golden JSON path
  cmsRun_script  path to hitEffFromRaw_cfg.py
  cmssw        release name, e.g. CMSSW_16_0_6
  outdir       output directory (/pnfs/... is copied with xrdcp)
"""

import argparse
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

REQUIRED = ["taskname", "sample", "runs", "maxevents", "recipe", "conditions",
            "cert", "cmsRun_script", "cmssw", "outdir"]

JOB_TEMPLATE = """#!/bin/bash -e
#SBATCH --account=t3
#SBATCH --partition=standard
#SBATCH --cpus-per-task=1
#SBATCH --mem=4000
#SBATCH --time={walltime}
#SBATCH --nodes=1
#SBATCH --job-name={taskname}
#SBATCH --array=1-{njobs}
#SBATCH --output={logdir}/%x_%A_%a.out
#SBATCH --error={logdir}/%x_%A_%a.err

set -e
echo "[`date`] job start, array task ${{SLURM_ARRAY_TASK_ID}}"

RUN=$(sed -n "${{SLURM_ARRAY_TASK_ID}}p" {taskdir}/runlist.txt)
FILELIST={taskdir}/filelists/input_run${{RUN}}.txt
OUTPUT=hitEff_run${{RUN}}.root

export SCRAM_ARCH={scram_arch}
source /cvmfs/cms.cern.ch/cmsset_default.sh
cd {cmsswbase}/src
eval `scramv1 runtime -sh`
cd $TMPDIR

FILES=$(paste -sd, {taskdir}/filelists/input_run${{RUN}}.txt)
echo "run ${{RUN}}, $(wc -l < $FILELIST) files, maxEvents={maxevents}"

cmsRun {cmsrun_script} \\
    recipe={recipe} \\
    globalTag={conditions} \\
    lumiMask={cert} \\
    maxEvents={maxevents} \\
    outputFileName=$OUTPUT \\
    inputFiles=$FILES

if [[ "{outdir}" == /pnfs/* ]]; then
    ( eval `scram unsetenv -sh`; gfal-mkdir -p root://t3dcachedb03.psi.ch:1094/{outdir} || true )
    xrdcp -f -N $OUTPUT root://t3dcachedb03.psi.ch:1094//{outdir}/$OUTPUT
else
    mkdir -p {outdir}
    cp $OUTPUT {outdir}/$OUTPUT
fi

echo "[`date`] job done"
"""


def das_files(dataset, run):
    """Files of one run, via dasgoclient."""
    q = "file dataset=%s run=%d" % (dataset, run)
    try:
        out = subprocess.run(["dasgoclient", "-query=" + q],
                             capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        sys.exit("dasgoclient not found -- run cmsenv first")
    if out.returncode != 0:
        print("  ! DAS query failed for run %d: %s" % (run, out.stderr.strip()))
        return []
    return [l.strip() for l in out.stdout.splitlines() if l.strip().endswith(".root")]


def create(cfg, args):
    taskdir = os.path.join(HERE, cfg["taskname"])
    filelists = os.path.join(taskdir, "filelists")
    logdir = os.path.join(taskdir, "logs")
    for d in (taskdir, filelists, logdir):
        os.makedirs(d, exist_ok=True)

    # Roughly how many files N events needs, so we do not stage more than
    # necessary. ZeroBias RAW is about 16k events per file. The floor of 3 is
    # insurance: the golden JSON removes lumisections, so a single shuffled
    # file could contribute far fewer events than its size suggests, or none.
    # cmsRun stops at maxEvents anyway, so extra files cost nothing.
    want_files = max(3, int(cfg["maxevents"] / 16000.0 * 3) + 1) if cfg["maxevents"] > 0 else 0

    kept_runs = []
    for run in cfg["runs"]:
        files = das_files(cfg["sample"], run)
        if not files:
            print("  run %d: no files, skipped" % run)
            continue
        # Fixed seed per run: reproducible, but not the lumisection order.
        random.Random(run).shuffle(files)
        if want_files:
            files = files[:want_files]
        path = os.path.join(filelists, "input_run%d.txt" % run)
        with open(path, "w") as fh:
            for f in files:
                fh.write("root://cms-xrd-global.cern.ch/" + f + "\n")
        kept_runs.append(run)
        print("  run %d: %d files" % (run, len(files)))

    if not kept_runs:
        sys.exit("no runs with files -- nothing to do")

    with open(os.path.join(taskdir, "runlist.txt"), "w") as fh:
        for r in kept_runs:
            fh.write("%d\n" % r)

    job = JOB_TEMPLATE.format(
        taskname=cfg["taskname"],
        taskdir=taskdir,
        logdir=logdir,
        njobs=len(kept_runs),
        walltime=cfg.get("walltime", "8:00:00"),
        scram_arch=os.environ.get("SCRAM_ARCH", "el9_amd64_gcc13"),
        cmsswbase=os.environ["CMSSW_BASE"],
        cmsrun_script=cfg["cmsRun_script"],
        recipe=cfg["recipe"],
        conditions=cfg["conditions"],
        cert=cfg["cert"],
        maxevents=cfg["maxevents"],
        outdir=cfg["outdir"],
    )
    jobpath = os.path.join(taskdir, "job.sh")
    with open(jobpath, "w") as fh:
        fh.write(job)
    os.chmod(jobpath, 0o755)

    print("\ntask     : %s" % taskdir)
    print("runs     : %d" % len(kept_runs))
    print("events   : %d per run" % cfg["maxevents"])
    print("estimate : ~%.1f CPU-hours total, ~%.1f GB of tree"
          % (len(kept_runs) * cfg["maxevents"] * 4.6 / 3600.0,
             len(kept_runs) * cfg["maxevents"] * 21.6e-6))
    print("\nsubmit with: %s --input %s --submit" % (sys.argv[0], args.input))


def submit(cfg, args):
    taskdir = os.path.join(HERE, cfg["taskname"])
    jobpath = os.path.join(taskdir, "job.sh")
    if not os.path.exists(jobpath):
        sys.exit("no job.sh in %s -- run --create first" % taskdir)
    print("$ sbatch %s" % jobpath)
    subprocess.call(["sbatch", jobpath])


def status(cfg, args):
    taskdir = os.path.join(HERE, cfg["taskname"])
    runlist = os.path.join(taskdir, "runlist.txt")
    if not os.path.exists(runlist):
        sys.exit("no runlist.txt in %s -- run --create first" % taskdir)
    runs = [int(l) for l in open(runlist) if l.strip()]

    done = 0
    outdir = cfg["outdir"]
    for run in runs:
        name = "hitEff_run%d.root" % run
        if outdir.startswith("/pnfs/"):
            rc = subprocess.run(["gfal-stat", "root://t3dcachedb03.psi.ch:1094/%s/%s" % (outdir, name)],
                                capture_output=True)
            if rc.returncode == 0:
                done += 1
        elif os.path.exists(os.path.join(outdir, name)):
            done += 1

    q = subprocess.run(["squeue", "-u", os.environ.get("USER", ""), "-h", "-o", "%t"],
                       capture_output=True, text=True)
    states = q.stdout.split() if q.returncode == 0 else []
    print("task      : %s" % cfg["taskname"])
    print("runs      : %d" % len(runs))
    print("completed : %d  (output file present)" % done)
    print("pending   : %d" % states.count("PD"))
    print("running   : %d" % states.count("R"))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", required=True, help="task config JSON")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--create", action="store_true")
    g.add_argument("--submit", action="store_true")
    g.add_argument("--status", action="store_true")
    args = p.parse_args()

    if "CMSSW_BASE" not in os.environ:
        sys.exit("CMSSW environment not set up -- run cmsenv first")

    with open(args.input) as fh:
        cfg = json.load(fh)
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        sys.exit("config is missing required fields: %s" % ", ".join(missing))
    if not cfg["runs"]:
        sys.exit("'runs' is empty -- this workflow takes an explicit run list")
    if not os.path.exists(cfg["cert"]):
        sys.exit("golden JSON not found: %s" % cfg["cert"])

    if args.create:
        create(cfg, args)
    elif args.submit:
        submit(cfg, args)
    else:
        status(cfg, args)


if __name__ == "__main__":
    main()
