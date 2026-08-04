"""Pixel hit efficiency from RAW: tracking-only reconstruction + slim tree.

Usage
-----
  cmsRun rawreco_hiteff_cfg.py recipe=2026 globalTag=160X_dataRun3_Prompt_v1 \
      inputFiles=root://cms-xrd-global.cern.ch//store/data/Run2026D/ZeroBias/RAW/... \
      maxEvents=500

The recipe must match the data-taking period, since it drives the pixel
reconstruction configuration:

  2025C, 2025D, 2025E     recipe=2025_AtoE        GT 150X_dataRun3_Prompt_v1
  2025F                   recipe=2025_F           GT 150X_dataRun3_Prompt_v1
  2025G                   recipe=2025_G           GT 150X_dataRun3_Prompt_v1
  2026, runs <  402532    recipe=2026_pre402532   GT 160X_dataRun3_Prompt_v1
  2026, runs >= 402532    recipe=2026             GT 160X_dataRun3_Prompt_v1
"""

import FWCore.ParameterSet.Config as cms
import FWCore.ParameterSet.VarParsing as VarParsing

opt = VarParsing.VarParsing("analysis")
opt.register("recipe", "2026",
             VarParsing.VarParsing.multiplicity.singleton,
             VarParsing.VarParsing.varType.string,
             "2025_AtoE | 2025_F | 2025_G | 2026_pre402532 | 2026")
opt.register("globalTag", "160X_dataRun3_Prompt_v1",
             VarParsing.VarParsing.multiplicity.singleton,
             VarParsing.VarParsing.varType.string, "global tag")
opt.register("outputFileName", "hitEff.root",
             VarParsing.VarParsing.multiplicity.singleton,
             VarParsing.VarParsing.varType.string, "output tree file")
opt.register("useFEDChannels", True,
             VarParsing.VarParsing.multiplicity.singleton,
             VarParsing.VarParsing.varType.bool,
             "mask ROCs flagged by the per-event PixelFEDChannel collection; "
             "set False only to measure what the FED errors are worth")
opt.register("lumiMask", "",
             VarParsing.VarParsing.multiplicity.singleton,
             VarParsing.VarParsing.varType.string,
             "certification (golden) JSON; empty means process everything")
opt.register("nThreads", 1,
             VarParsing.VarParsing.multiplicity.singleton,
             VarParsing.VarParsing.varType.int, "number of threads")
opt.setDefault("maxEvents", -1)
opt.parseArguments()

# ---------------------------------------------------------------------------
# Era recipe.
#
#   2025A-E   Run3_2025 minus siPixelGoodEdgeAlgo and siPixelDigiMorphing,
#             plus PixelCPEGenericESProducer.IrradiationBiasCorrection = True
#   2025F     Run3_2025 minus siPixelDigiMorphing
#   2025G     Run3_2025 unmodified
#   2026      Run3_2025 for runs < 402532, Run3_2026 from 402532 on
# ---------------------------------------------------------------------------
_irradiationBiasCorrection = False

if opt.recipe == "2025_AtoE":
    from Configuration.Eras.Era_Run3_2025_cff import Run3_2025
    from Configuration.ProcessModifiers.siPixelGoodEdgeAlgo_cff import siPixelGoodEdgeAlgo
    from Configuration.ProcessModifiers.siPixelDigiMorphing_cff import siPixelDigiMorphing
    _era = cms.ModifierChain(Run3_2025.copyAndExclude([siPixelGoodEdgeAlgo, siPixelDigiMorphing]))
    _irradiationBiasCorrection = True
elif opt.recipe == "2025_F": # IBC off
    from Configuration.Eras.Era_Run3_2025_cff import Run3_2025
    from Configuration.ProcessModifiers.siPixelDigiMorphing_cff import siPixelDigiMorphing
    _era = cms.ModifierChain(Run3_2025.copyAndExclude([siPixelDigiMorphing]))
elif opt.recipe in ("2025_G", "2026_pre402532"): # IBC off + Digi-morphing
    from Configuration.Eras.Era_Run3_2025_cff import Run3_2025
    _era = Run3_2025
elif opt.recipe == "2026": # IBC off + Digi-morphing + Generic-only reco
    from Configuration.Eras.Era_Run3_2026_cff import Run3_2026
    _era = Run3_2026
else:
    raise RuntimeError(
        "unknown recipe '%s'; expected one of "
        "2025_AtoE, 2025_F, 2025_G, 2026_pre402532, 2026" % opt.recipe)

process = cms.Process("HITEFF", _era)

process.load("Configuration.StandardSequences.Services_cff")
process.load("Configuration.StandardSequences.GeometryRecoDB_cff")
process.load("Configuration.StandardSequences.MagneticField_cff")
process.load("Configuration.StandardSequences.RawToDigi_Data_cff")
process.load("Configuration.StandardSequences.Reconstruction_Data_cff")
process.load("Configuration.StandardSequences.FrontierConditions_GlobalTag_cff")
process.load("RecoTracker.TrackProducer.TrackRefitters_cff")

from Configuration.AlCa.GlobalTag import GlobalTag
process.GlobalTag = GlobalTag(process.GlobalTag, opt.globalTag, "")

process.load("FWCore.MessageService.MessageLogger_cfi")
process.MessageLogger.cerr.FwkReport.reportEvery = 500
process.MessageLogger.cerr.threshold = "WARNING"
process.MessageLogger.cerr.BasicTrajectoryState = cms.untracked.PSet(limit=cms.untracked.int32(5))
process.MessageLogger.cerr.TrackNaN = cms.untracked.PSet(limit=cms.untracked.int32(5))

process.maxEvents = cms.untracked.PSet(input=cms.untracked.int32(opt.maxEvents))
process.source = cms.Source("PoolSource",
                            fileNames=cms.untracked.vstring(opt.inputFiles),
                            secondaryFileNames=cms.untracked.vstring())

if opt.lumiMask:
    import FWCore.PythonUtilities.LumiList as LumiList
    process.source.lumisToProcess = LumiList.LumiList(
        filename=opt.lumiMask).getVLuminosityBlockRange()

process.options = cms.untracked.PSet(
    numberOfThreads=cms.untracked.uint32(opt.nThreads),
    numberOfStreams=cms.untracked.uint32(opt.nThreads),
    wantSummary=cms.untracked.bool(True),
)

process.TFileService = cms.Service("TFileService",
                                   fileName=cms.string(opt.outputFileName))

process.TrackRefitter.src = "generalTracks"
process.TrackRefitter.TrajectoryInEvent = True

# Which CPE sits inside this builder is era dependent: the PixelCPEGeneric
# process modifier, carried by Run3_2026, rewrites WithAngleAndTemplate from
# PixelCPEClusterRepair to PixelCPEGeneric. The analyzer is given the same name
# so cluster positions come from whatever tracking used -- the alignment is only
# valid for that algorithm. Defined once here so the two cannot drift apart.
ttrhBuilder = "WithAngleAndTemplate"
process.TrackRefitter.TTRHBuilder = ttrhBuilder

# We almost surely want to use that
if not opt.useFEDChannels:
    process.MeasurementTrackerEvent.badPixelFEDChannelCollectionLabels = cms.VInputTag()

process.hitEff = cms.EDAnalyzer(
    "SiPixelHitEffTree",
    trajectoryInput=cms.InputTag("TrackRefitter"),
    pixelRecHits=cms.InputTag("siPixelRecHits"),
    primaryVertices=cms.InputTag("offlinePrimaryVertices"),
    measurementTrackerEvent=cms.InputTag("MeasurementTrackerEvent"),
    propagator=cms.string("PropagatorWithMaterial"),
    estimator=cms.string("Chi2"),
    ttrhBuilder=cms.string(ttrhBuilder),
    trackPtCut=cms.double(1.0),
    trackNStripCut=cms.int32(10),
    vertexNTrackCut=cms.int32(10),
    requireHighPurity=cms.bool(True),
)

process.raw2digi_step = cms.Path(process.RawToDigi)
process.reconstruction_step = cms.Path(process.reconstruction_trackingOnly)
process.refit_step = cms.Path(process.MeasurementTrackerEvent * process.TrackRefitter)
process.ana_step = cms.Path(process.hitEff)

process.schedule = cms.Schedule(process.raw2digi_step,
                                process.reconstruction_step,
                                process.refit_step,
                                process.ana_step)

if _irradiationBiasCorrection:
    process.PixelCPEGenericESProducer.IrradiationBiasCorrection = True

# Reduces peak memory; harmless here but the grid cares.
from Configuration.StandardSequences.earlyDeleteSettings_cff import customiseEarlyDelete
process = customiseEarlyDelete(process)
