// -*- C++ -*-
//
// Package:    SiPixelTools/PhaseIPixelNtuplizer
// Class:      SiPixelHitEffTree
//
/*
  Slim flat tree for the Run 3 pixel hit-efficiency trend measurement.
*/

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <memory>
#include <utility>
#include <vector>

#include "FWCore/Framework/interface/Event.h"
#include "FWCore/Framework/interface/EventSetup.h"
#include "FWCore/Framework/interface/Frameworkfwd.h"
#include "FWCore/Framework/interface/MakerMacros.h"
#include "FWCore/Framework/interface/one/EDAnalyzer.h"
#include "FWCore/MessageLogger/interface/MessageLogger.h"
#include "FWCore/ParameterSet/interface/ConfigurationDescriptions.h"
#include "FWCore/ParameterSet/interface/ParameterSet.h"
#include "FWCore/ParameterSet/interface/ParameterSetDescription.h"
#include "FWCore/ServiceRegistry/interface/Service.h"
#include "FWCore/Utilities/interface/Exception.h"
#include "CommonTools/UtilAlgos/interface/TFileService.h"

#include "DataFormats/Common/interface/DetSetVectorNew.h"
#include "DataFormats/SiPixelCluster/interface/SiPixelCluster.h"
#include "DataFormats/SiPixelDetId/interface/PixelSubdetector.h"
#include "DataFormats/TrackReco/interface/Track.h"
#include "DataFormats/TrackReco/interface/TrackFwd.h"
#include "DataFormats/TrackerCommon/interface/TrackerTopology.h"
#include "DataFormats/TrackerRecHit2D/interface/SiPixelRecHit.h"
#include "DataFormats/VertexReco/interface/Vertex.h"
#include "DataFormats/VertexReco/interface/VertexFwd.h"

#include "TrackingTools/GeomPropagators/interface/Propagator.h"
#include "TrackingTools/KalmanUpdators/interface/Chi2MeasurementEstimatorBase.h"
#include "TrackingTools/MeasurementDet/interface/LayerMeasurements.h"
#include "TrackingTools/PatternTools/interface/TrajTrackAssociation.h"
#include "TrackingTools/PatternTools/interface/Trajectory.h"
#include "TrackingTools/TrackFitters/interface/TrajectoryStateCombiner.h"
#include "TrackingTools/Records/interface/TrackingComponentsRecord.h"
#include "TrackingTools/TrajectoryState/interface/TrajectoryStateOnSurface.h"

#include "RecoTracker/MeasurementDet/interface/MeasurementTracker.h"
#include "RecoTracker/MeasurementDet/interface/MeasurementTrackerEvent.h"
#include "RecoTracker/Record/interface/CkfComponentsRecord.h"
#include "TrackingTools/Records/interface/TransientRecHitRecord.h"
#include "TrackingTools/TransientTrackingRecHit/interface/TransientTrackingRecHitBuilder.h"
#include "RecoTracker/TransientTrackingRecHit/interface/TkTransientTrackingRecHitBuilder.h"
#include "RecoTracker/TransientTrackingRecHit/interface/TkClonerImpl.h"
#include "DataFormats/TrackerRecHit2D/interface/SiPixelRecHitCollection.h"

#include "Geometry/CommonDetUnit/interface/PixelGeomDetUnit.h"
#include "Geometry/CommonTopologies/interface/PixelTopology.h"
#include "Geometry/Records/interface/TrackerDigiGeometryRecord.h"
#include "Geometry/Records/interface/TrackerTopologyRcd.h"
#include "Geometry/TrackerGeometryBuilder/interface/TrackerGeometry.h"
#include "TrackingTools/DetLayers/interface/DetLayer.h"
#include "RecoTracker/TkDetLayers/interface/GeometricSearchTracker.h"

#include "CondFormats/DataRecord/interface/SiPixelFedCablingMapRcd.h"
#include "CondFormats/SiPixelObjects/interface/SiPixelFedCablingMap.h"

#include "DQM/SiPixelPhase1Common/interface/SiPixelCoordinates.h"

#include "TTree.h"

namespace {
  constexpr float kNoVal = -9999.f;

  // Combined forward/backward state, as PhaseIPixelNtuplizer uses: the unbiased
  // trajectory position on the module, which is what the residual to the
  // nearest cluster must be measured from.
  TrajectoryStateOnSurface combinedState(const TrajectoryMeasurement& m) {
    static TrajectoryStateCombiner combiner;
    const auto& fwd = m.forwardPredictedState();
    const auto& bwd = m.backwardPredictedState();
    if (fwd.isValid() && bwd.isValid())
      return combiner(fwd, bwd);
    if (bwd.isValid())
      return bwd;
    if (fwd.isValid())
      return fwd;
    return TrajectoryStateOnSurface();
  }

  bool isPixel(const DetId& id) {
    return id.det() == DetId::Tracker && (id.subdetId() == PixelSubdetector::PixelBarrel ||
                                          id.subdetId() == PixelSubdetector::PixelEndcap);
  }

  using MeasByDet = std::map<uint32_t, std::vector<std::pair<const reco::Track*, LocalPoint>>>;
}  // namespace

class SiPixelHitEffTree : public edm::one::EDAnalyzer<edm::one::SharedResources> {
public:
  explicit SiPixelHitEffTree(const edm::ParameterSet&);
  ~SiPixelHitEffTree() override = default;

  static void fillDescriptions(edm::ConfigurationDescriptions&);

private:
  void analyze(const edm::Event&, const edm::EventSetup&) override;
  void endJob() override;

  void fillModuleFields(const DetId&, const LocalPoint&, const SiPixelRecHit* validRecHit);
  void fillRow(const TrajectoryMeasurement&,
               const TrajectoryStateOnSurface&,
               const SiPixelRecHitCollection&,
               const MeasByDet&,
               const reco::Track*);

  // ---- configuration ----
  const edm::EDGetTokenT<TrajTrackAssociationCollection> trajTrackToken_;
  const edm::EDGetTokenT<SiPixelRecHitCollection> recHitToken_;
  const edm::EDGetTokenT<reco::VertexCollection> vertexToken_;
  const edm::EDGetTokenT<MeasurementTrackerEvent> measTrackerEventToken_;

  const edm::ESGetToken<TrackerGeometry, TrackerDigiGeometryRecord> geomToken_;
  const edm::ESGetToken<TrackerTopology, TrackerTopologyRcd> topoToken_;
  const edm::ESGetToken<SiPixelFedCablingMap, SiPixelFedCablingMapRcd> cablingToken_;
  const edm::ESGetToken<MeasurementTracker, CkfComponentsRecord> measTrackerToken_;
  const edm::ESGetToken<Propagator, TrackingComponentsRecord> propagatorToken_;
  const edm::ESGetToken<Chi2MeasurementEstimatorBase, TrackingComponentsRecord> estimatorToken_;
  // Resolved by NAME, deliberately: which CPE lives inside "WithAngleAndTemplate"
  // is era dependent -- the PixelCPEGeneric process modifier, which Run3_2026
  // carries, rewrites it from PixelCPEClusterRepair to PixelCPEGeneric (see
  // RecoTracker/TransientTrackingRecHit/python/TTRHBuilderWithTemplate_cfi.py).
  // Naming the builder rather than a CPE means cluster positions always come
  // from whatever tracking itself used, which is what the alignment is tied to.
  // Configure it from the same value as TrackRefitter.TTRHBuilder.
  const edm::ESGetToken<TransientTrackingRecHitBuilder, TransientRecHitRecord> ttrhBuilderToken_;
  const std::string ttrhBuilderName_;

  const double trackPtCut_;
  const int trackNStripCut_;
  const int vertexNTrackCut_;
  const bool requireHighPurity_;

  // ---- transient ----
  SiPixelCoordinates coord_;
  const TrackerGeometry* geom_ = nullptr;
  const TransientTrackingRecHitBuilder* ttrhBuilder_ = nullptr;
  // Held by value: cloner() returns a TkClonerImpl built from the builder's
  // CPEs. Rebuilt whenever the builder changes, i.e. once per event.
  std::unique_ptr<TkClonerImpl> cloner_;

  unsigned long long nEvents_ = 0;
  unsigned long long nRows_ = 0;
  unsigned long long nTracksUsed_ = 0;
  unsigned long long nL1Propagated_ = 0;
  unsigned long long nL1Ambiguous_ = 0;
  unsigned long long nL1NoCandidate_ = 0;
  unsigned long long nL1TsosInvalid_ = 0;

  // ---- tree ----
  TTree* tree_ = nullptr;

  UInt_t b_run_, b_ls_;
  Int_t b_nvtx_, b_vtx_ntrk_;

  UInt_t b_detid_;
  Int_t b_roc_;
  Int_t b_det_, b_layer_, b_disk_, b_ladder_, b_module_, b_blade_, b_panel_, b_ring_;
  Float_t b_module_coord_, b_ladder_coord_, b_disk_ring_coord_, b_blade_panel_coord_;

  // 0 valid, 1 missing, 2 inactive, -1 other.
  Int_t b_status_;
  Float_t b_lx_, b_ly_, b_lx_err_, b_ly_err_;
  Float_t b_dx_cl_, b_dy_cl_, b_d_cl_;
  Float_t b_d_tr_;

  Float_t b_trk_pt_, b_trk_eta_, b_trk_phi_, b_trk_d0_, b_trk_dz_;
  Int_t b_trk_nstrip_;
  Int_t b_trk_validbpix_[4], b_trk_validfpix_[3];
};

SiPixelHitEffTree::SiPixelHitEffTree(const edm::ParameterSet& iConfig)
    : trajTrackToken_(consumes<TrajTrackAssociationCollection>(iConfig.getParameter<edm::InputTag>("trajectoryInput"))),
      recHitToken_(consumes<SiPixelRecHitCollection>(iConfig.getParameter<edm::InputTag>("pixelRecHits"))),
      vertexToken_(consumes<reco::VertexCollection>(iConfig.getParameter<edm::InputTag>("primaryVertices"))),
      measTrackerEventToken_(
          consumes<MeasurementTrackerEvent>(iConfig.getParameter<edm::InputTag>("measurementTrackerEvent"))),
      geomToken_(esConsumes()),
      topoToken_(esConsumes()),
      cablingToken_(esConsumes()),
      measTrackerToken_(esConsumes()),
      propagatorToken_(esConsumes(edm::ESInputTag("", iConfig.getParameter<std::string>("propagator")))),
      estimatorToken_(esConsumes(edm::ESInputTag("", iConfig.getParameter<std::string>("estimator")))),
      ttrhBuilderToken_(esConsumes(edm::ESInputTag("", iConfig.getParameter<std::string>("ttrhBuilder")))),
      ttrhBuilderName_(iConfig.getParameter<std::string>("ttrhBuilder")),
      trackPtCut_(iConfig.getParameter<double>("trackPtCut")),
      trackNStripCut_(iConfig.getParameter<int>("trackNStripCut")),
      vertexNTrackCut_(iConfig.getParameter<int>("vertexNTrackCut")),
      requireHighPurity_(iConfig.getParameter<bool>("requireHighPurity")) {
  usesResource("TFileService");
  edm::Service<TFileService> fs;
  tree_ = fs->make<TTree>("hitEff", "pixel hit efficiency, one row per trajectory measurement");

  tree_->Branch("run", &b_run_, "run/i");
  tree_->Branch("ls", &b_ls_, "ls/i");
  tree_->Branch("nvtx", &b_nvtx_, "nvtx/I");
  tree_->Branch("vtx_ntrk", &b_vtx_ntrk_, "vtx_ntrk/I");

  tree_->Branch("detid", &b_detid_, "detid/i");
  tree_->Branch("roc", &b_roc_, "roc/I");
  tree_->Branch("det", &b_det_, "det/I");
  tree_->Branch("layer", &b_layer_, "layer/I");
  tree_->Branch("disk", &b_disk_, "disk/I");
  tree_->Branch("ladder", &b_ladder_, "ladder/I");
  tree_->Branch("module", &b_module_, "module/I");
  tree_->Branch("blade", &b_blade_, "blade/I");
  tree_->Branch("panel", &b_panel_, "panel/I");
  tree_->Branch("ring", &b_ring_, "ring/I");
  tree_->Branch("module_coord", &b_module_coord_, "module_coord/F");
  tree_->Branch("ladder_coord", &b_ladder_coord_, "ladder_coord/F");
  tree_->Branch("disk_ring_coord", &b_disk_ring_coord_, "disk_ring_coord/F");
  tree_->Branch("blade_panel_coord", &b_blade_panel_coord_, "blade_panel_coord/F");

  tree_->Branch("status", &b_status_, "status/I");
  tree_->Branch("lx", &b_lx_, "lx/F");
  tree_->Branch("ly", &b_ly_, "ly/F");
  tree_->Branch("lx_err", &b_lx_err_, "lx_err/F");
  tree_->Branch("ly_err", &b_ly_err_, "ly_err/F");
  tree_->Branch("dx_cl", &b_dx_cl_, "dx_cl/F");
  tree_->Branch("dy_cl", &b_dy_cl_, "dy_cl/F");
  tree_->Branch("d_cl", &b_d_cl_, "d_cl/F");
  tree_->Branch("d_tr", &b_d_tr_, "d_tr/F");

  tree_->Branch("trk_pt", &b_trk_pt_, "trk_pt/F");
  tree_->Branch("trk_eta", &b_trk_eta_, "trk_eta/F");
  tree_->Branch("trk_phi", &b_trk_phi_, "trk_phi/F");
  tree_->Branch("trk_d0", &b_trk_d0_, "trk_d0/F");
  tree_->Branch("trk_dz", &b_trk_dz_, "trk_dz/F");
  tree_->Branch("trk_nstrip", &b_trk_nstrip_, "trk_nstrip/I");
  tree_->Branch("trk_validbpix", b_trk_validbpix_, "trk_validbpix[4]/I");
  tree_->Branch("trk_validfpix", b_trk_validfpix_, "trk_validfpix[3]/I");
}

void SiPixelHitEffTree::fillDescriptions(edm::ConfigurationDescriptions& descriptions) {
  edm::ParameterSetDescription desc;
  desc.add<edm::InputTag>("trajectoryInput", edm::InputTag("TrackRefitter"));
  desc.add<edm::InputTag>("pixelRecHits", edm::InputTag("siPixelRecHits"));
  desc.add<edm::InputTag>("primaryVertices", edm::InputTag("offlinePrimaryVertices"));
  desc.add<edm::InputTag>("measurementTrackerEvent", edm::InputTag("MeasurementTrackerEvent"));
  desc.add<std::string>("propagator", "PropagatorWithMaterial");
  desc.add<std::string>("estimator", "Chi2");
  desc.add<std::string>("ttrhBuilder", "WithAngleAndTemplate")
      ->setComment("must match TrackRefitter.TTRHBuilder: it selects the era-appropriate "
                   "pixel CPE, and the alignment is only valid for the algorithm tracking used");
  desc.add<double>("trackPtCut", 1.0);
  desc.add<int>("trackNStripCut", 10);
  desc.add<int>("vertexNTrackCut", 10);
  desc.add<bool>("requireHighPurity", true);
  descriptions.addWithDefaultLabel(desc);
}

void SiPixelHitEffTree::fillModuleFields(const DetId& detId,
                                         const LocalPoint& localPos,
                                         const SiPixelRecHit* validRecHit) {
  b_detid_ = detId.rawId();
  b_det_ = detId.subdetId() - 1;  // 0 = BPIX, 1 = FPIX
  b_layer_ = b_disk_ = b_ladder_ = b_module_ = b_blade_ = b_panel_ = b_ring_ = -9999;
  b_module_coord_ = b_ladder_coord_ = b_disk_ring_coord_ = b_blade_panel_coord_ = kNoVal;

  if (detId.subdetId() == PixelSubdetector::PixelBarrel) {
    b_layer_ = coord_.layer(detId);
    b_ladder_ = coord_.signed_ladder(detId);
    b_module_ = coord_.signed_module(detId);
  } else {
    b_disk_ = coord_.signed_disk(detId);
    b_blade_ = coord_.signed_blade(detId);
    b_panel_ = coord_.panel(detId);
    b_ring_ = coord_.ring(detId);
    b_module_ = coord_.module(detId);
  }

  // ROC number and the online signed coordinates need a pixel on the module.
  // A valid hit supplies its own; otherwise convert the trajectory position to
  // row/col, as PhaseIPixelNtuplizer does for missing hits.
  if (validRecHit != nullptr) {
    b_roc_ = coord_.roc(validRecHit);
    b_module_coord_ = coord_.signed_module_coord(validRecHit);
    b_ladder_coord_ = coord_.signed_ladder_coord(validRecHit);
    b_disk_ring_coord_ = coord_.signed_disk_ring_coord(validRecHit);
    b_blade_panel_coord_ = coord_.signed_shifted_blade_panel_coord(validRecHit);
    return;
  }

  int row = 0, col = 0;
  const auto* pgdu = dynamic_cast<const PixelGeomDetUnit*>(geom_->idToDetUnit(detId));
  if (pgdu != nullptr) {
    const PixelTopology& topo = pgdu->specificTopology();
    MeasurementPoint mp = topo.measurementPosition(localPos);
    row = std::max(0, std::min(topo.nrows() - 1, static_cast<int>(mp.x())));
    col = std::max(0, std::min(topo.ncolumns() - 1, static_cast<int>(mp.y())));
  }
  const std::pair<int, int> pixel(row, col);
  b_roc_ = coord_.roc(detId, pixel);
  b_module_coord_ = coord_.signed_module_coord(detId, pixel);
  b_ladder_coord_ = coord_.signed_ladder_coord(detId, pixel);
  b_disk_ring_coord_ = coord_.signed_disk_ring_coord(detId, pixel);
  b_blade_panel_coord_ = coord_.signed_shifted_blade_panel_coord(detId, pixel);
}

void SiPixelHitEffTree::fillRow(const TrajectoryMeasurement& meas,
                                const TrajectoryStateOnSurface& tsos,
                                const SiPixelRecHitCollection& pixelRecHits,
                                const MeasByDet& measByDet,
                                const reco::Track* track) {
  const auto recHit = meas.recHit();
  const DetId detId = recHit->geographicalId();

  const LocalPoint lp = tsos.localPosition();
  const LocalError le = tsos.localError().positionError();
  b_lx_ = lp.x();
  b_ly_ = lp.y();
  b_lx_err_ = le.xx();
  b_ly_err_ = le.yy();

  const bool valid = recHit->getType() == TrackingRecHit::valid;
  const bool missing = recHit->getType() == TrackingRecHit::missing;
  const bool inactive = recHit->getType() == TrackingRecHit::inactive;
  b_status_ = valid ? 0 : (missing ? 1 : (inactive ? 2 : -1));

  const SiPixelRecHit* pixHit = valid ? dynamic_cast<const SiPixelRecHit*>(recHit->hit()) : nullptr;
  fillModuleFields(detId, lp, pixHit);

  // Nearest hit on this module, measured from the trajectory position, in local
  // x and y separately so any recovery distance stays recomputable.
  //
  // Every hit is re-evaluated through TkCloner rather than taken at its stored
  // position. The cloner runs pixelCPE->getParameters(cluster, detUnit, tsos),
  // so it applies the track angle AND the CPE that lives inside the configured
  // builder -- templates for 2025, generic for 2026, per the PixelCPEGeneric
  // process modifier. Tracking used that same combination, and the alignment is
  // only valid for it.
  //
  // setDet is required. Hits read from the persistent siPixelRecHits collection
  // carry no geometry pointer, and the cloner dereferences hit.detUnit() and
  // hit.det() unconditionally.
  b_dx_cl_ = b_dy_cl_ = b_d_cl_ = kNoVal;
  const GeomDet* gdet = geom_->idToDet(detId);
  auto detSet = pixelRecHits.find(detId.rawId());
  if (cloner_ != nullptr && gdet != nullptr && tsos.isValid() && detSet != pixelRecHits.end()) {
    float best = 1e4f;
    for (const auto& hit : *detSet) {
      SiPixelRecHit attached(hit);
      attached.setDet(*gdet);
      auto refit = (*cloner_)(attached, tsos);
      if (!refit)
        continue;
      const LocalPoint clp = refit->localPosition();
      const float ddx = std::abs(clp.x() - b_lx_);
      const float ddy = std::abs(clp.y() - b_ly_);
      const float d = std::sqrt(ddx * ddx + ddy * ddy);
      if (d < best) {
        best = d;
        b_dx_cl_ = ddx;
        b_dy_cl_ = ddy;
        b_d_cl_ = d;
      }
    }
  }

  // Closest measurement of any *other* track on this same module.
  b_d_tr_ = 9999.f;
  auto sameDet = measByDet.find(detId.rawId());
  if (sameDet != measByDet.end()) {
    for (const auto& other : sameDet->second) {
      if (other.first == track)
        continue;
      const float ddx = other.second.x() - b_lx_;
      const float ddy = other.second.y() - b_ly_;
      const float d = std::sqrt(ddx * ddx + ddy * ddy);
      if (d < b_d_tr_)
        b_d_tr_ = d;
    }
  }

  tree_->Fill();
  ++nRows_;
}

void SiPixelHitEffTree::analyze(const edm::Event& iEvent, const edm::EventSetup& iSetup) {
  ++nEvents_;
  b_run_ = iEvent.id().run();
  b_ls_ = iEvent.luminosityBlock();

  geom_ = &iSetup.getData(geomToken_);
  const TrackerTopology& topo = iSetup.getData(topoToken_);
  const SiPixelFedCablingMap& cabling = iSetup.getData(cablingToken_);
  coord_.init(&topo, geom_, &cabling);

  const MeasurementTracker& measTracker = iSetup.getData(measTrackerToken_);
  const Chi2MeasurementEstimatorBase& estimator = iSetup.getData(estimatorToken_);
  ttrhBuilder_ = &iSetup.getData(ttrhBuilderToken_);
  // cloner() lives on the concrete Tk builder, not on the abstract interface
  // the record hands back.
  if (const auto* tkBuilder = dynamic_cast<const TkTransientTrackingRecHitBuilder*>(ttrhBuilder_)) {
    cloner_ = std::make_unique<TkClonerImpl>(tkBuilder->cloner());
  } else {
    throw cms::Exception("Configuration")
        << "ttrhBuilder '" << ttrhBuilderName_ << "' is not a TkTransientTrackingRecHitBuilder, "
        << "so pixel hit positions cannot be recomputed with the era's CPE";
  }

  std::unique_ptr<Propagator> propagator(iSetup.getData(propagatorToken_).clone());
  propagator->setPropagationDirection(oppositeToMomentum);

  edm::Handle<TrajTrackAssociationCollection> trajTracks;
  iEvent.getByToken(trajTrackToken_, trajTracks);
  edm::Handle<SiPixelRecHitCollection> pixelRecHits;
  iEvent.getByToken(recHitToken_, pixelRecHits);
  edm::Handle<reco::VertexCollection> vertices;
  iEvent.getByToken(vertexToken_, vertices);
  edm::Handle<MeasurementTrackerEvent> measTrackerEvent;
  iEvent.getByToken(measTrackerEventToken_, measTrackerEvent);

  if (!trajTracks.isValid() || !pixelRecHits.isValid() || !measTrackerEvent.isValid())
    return;

  b_nvtx_ = vertices.isValid() ? static_cast<int>(vertices->size()) : 0;

  // Index every pixel measurement of every track by DetId once, so the hit
  // separation lookup is not quadratic in track multiplicity.
  MeasByDet measByDet;
  for (const auto& pair : *trajTracks) {
    const reco::Track* trk = pair.val.get();
    for (const auto& m : pair.key->measurements()) {
      const DetId id = m.recHit()->geographicalId();
      if (!isPixel(id))
        continue;
      const TrajectoryStateOnSurface s = combinedState(m);
      if (!s.isValid())
        continue;
      measByDet[id.rawId()].emplace_back(trk, s.localPosition());
    }
  }

  const DetLayer* pxb1 = measTracker.geometricSearchTracker()->pixelBarrelLayers().front();
  LayerMeasurements layerMeasurements(measTracker, *measTrackerEvent);

  for (const auto& pair : *trajTracks) {
    const edm::Ref<std::vector<Trajectory>> traj = pair.key;
    const reco::TrackRef trackRef = pair.val;
    const reco::Track* track = trackRef.get();

    // ---- track-level selection (everything layer-dependent is stored, not cut) ----
    if (requireHighPurity_ && !track->quality(reco::TrackBase::highPurity))
      continue;
    if (track->pt() <= trackPtCut_)
      continue;
    const int nstrip = track->hitPattern().numberOfValidStripHits();
    if (nstrip <= trackNStripCut_)
      continue;

    const reco::Vertex* closestVertex = nullptr;
    double bestDz = 1e9;
    if (vertices.isValid()) {
      for (const auto& v : *vertices) {
        const double dz = std::abs(track->dz(v.position()));
        if (dz < bestDz) {
          bestDz = dz;
          closestVertex = &v;
        }
      }
    }
    b_vtx_ntrk_ = closestVertex ? static_cast<int>(closestVertex->tracksSize()) : 0;
    if (b_vtx_ntrk_ <= vertexNTrackCut_)
      continue;

    b_trk_pt_ = track->pt();
    b_trk_eta_ = track->eta();
    b_trk_phi_ = track->phi();
    b_trk_nstrip_ = nstrip;
    b_trk_d0_ = closestVertex ? -1.0 * track->dxy(closestVertex->position()) : track->d0();
    b_trk_dz_ = closestVertex ? track->dz(closestVertex->position()) : track->dz();

    // Valid pixel hits per layer/disk on this track, for the pixhit cut later.
    std::fill(std::begin(b_trk_validbpix_), std::end(b_trk_validbpix_), 0);
    std::fill(std::begin(b_trk_validfpix_), std::end(b_trk_validfpix_), 0);
    for (const auto& m : traj->measurements()) {
      const DetId id = m.recHit()->geographicalId();
      if (!isPixel(id) || m.recHit()->getType() != TrackingRecHit::valid)
        continue;
      if (id.subdetId() == PixelSubdetector::PixelBarrel) {
        const int l = topo.pxbLayer(id);
        if (l >= 1 && l <= 4)
          ++b_trk_validbpix_[l - 1];
      } else {
        const int d = topo.pxfDisk(id);
        if (d >= 1 && d <= 3)
          ++b_trk_validfpix_[d - 1];
      }
    }
    ++nTracksUsed_;

    // ---- measurements already on the trajectory, L1 excluded ----
    //
    // The same pass picks the anchor the L1 propagation starts from: the
    // innermost measurement that is not itself on L1 and can be propagated
    // from. Selected by radius.
    const auto& measurements = traj->measurements();
    auto anchor = measurements.end();
    float anchorR = std::numeric_limits<float>::max();
    for (auto it = measurements.begin(); it != measurements.end(); ++it) {
      const DetId id = it->recHit()->geographicalId();
      const bool isL1 =
          isPixel(id) && (id.subdetId() == PixelSubdetector::PixelBarrel) && (topo.pxbLayer(id) == 1);

      if (!isL1 && id.rawId() != 0 && it->recHit()->isValid() && it->updatedState().isValid()) {
        const float r = it->updatedState().globalPosition().perp();
        if (r < anchorR) {
          anchorR = r;
          anchor = it;
        }
      }

      if (!isPixel(id) || isL1)
        continue;  // L1 is handled by our own propagation below
      const TrajectoryStateOnSurface tsos = combinedState(*it);
      if (!tsos.isValid())
        continue;
      fillRow(*it, tsos, *pixelRecHits, measByDet, track);
    }

    // ---- our own propagation to L1 ----
    if (anchor == measurements.end())
      continue;  // nothing outside L1 to propagate from

    const auto candidates =
        layerMeasurements.measurements(*pxb1, anchor->updatedState(), *propagator, estimator);

    // Keep the valid measurement per module if there is one, then require that
    // exactly one module is compatible: only one can be the real crossing, so
    // accepting several would manufacture missing hits.
    std::map<uint32_t, const TrajectoryMeasurement*> byDetId;
    for (const auto& candidate : candidates) {
      const DetId candidateId = candidate.recHit()->geographicalId();
      // A compatible-det search can return an invalid hit carrying no DetId at
      // all; it points at no module and must not be counted either way.
      if (candidateId.rawId() == 0 || !isPixel(candidateId))
        continue;
      const uint32_t id = candidateId.rawId();
      auto found = byDetId.find(id);
      if (found == byDetId.end()) {
        byDetId[id] = &candidate;
      } else if (candidate.recHit()->getType() == TrackingRecHit::valid &&
                 found->second->recHit()->getType() != TrackingRecHit::valid) {
        found->second = &candidate;
      }
    }
    if (byDetId.size() != 1) {
      if (byDetId.size() > 1)
        ++nL1Ambiguous_;
      else
        ++nL1NoCandidate_;
      continue;
    }

    const TrajectoryMeasurement& l1Meas = *byDetId.begin()->second;
    const TrajectoryStateOnSurface l1Tsos = combinedState(l1Meas);
    if (!l1Tsos.isValid()) {
      // Expected to stay at zero. For debugging, check if this happens.
      ++nL1TsosInvalid_;
      continue;
    }
    ++nL1Propagated_;
    fillRow(l1Meas, l1Tsos, *pixelRecHits, measByDet, track);
  }
}

void SiPixelHitEffTree::endJob() {
  edm::LogPrint("SiPixelHitEffTree") << "\n===== SiPixelHitEffTree summary =====";
  edm::LogPrint("SiPixelHitEffTree") << "events processed          : " << nEvents_;
  edm::LogPrint("SiPixelHitEffTree") << "tracks passing selection  : " << nTracksUsed_;
  edm::LogPrint("SiPixelHitEffTree") << "rows written              : " << nRows_;
  edm::LogPrint("SiPixelHitEffTree") << "L1 measurements propagated: " << nL1Propagated_;
  edm::LogPrint("SiPixelHitEffTree") << "  L1 dropped, >1 module    : " << nL1Ambiguous_;
  edm::LogPrint("SiPixelHitEffTree") << "  L1 dropped, no candidate : " << nL1NoCandidate_;
  edm::LogPrint("SiPixelHitEffTree") << "  L1 dropped, invalid TSOS : " << nL1TsosInvalid_;
  if (nEvents_ > 0)
    edm::LogPrint("SiPixelHitEffTree") << "rows per event            : "
                                       << static_cast<double>(nRows_) / static_cast<double>(nEvents_);
  edm::LogPrint("SiPixelHitEffTree") << "=====================================";
}

DEFINE_FWK_MODULE(SiPixelHitEffTree);
