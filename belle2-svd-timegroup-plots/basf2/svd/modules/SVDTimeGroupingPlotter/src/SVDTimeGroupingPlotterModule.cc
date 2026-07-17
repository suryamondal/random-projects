/**************************************************************************
 * basf2 (Belle II Analysis Software Framework)                           *
 * Author: The Belle II Collaboration                                     *
 *                                                                        *
 * See git log for contributors and copyright holders.                    *
 * This file is licensed under LGPL-3.0, see LICENSE.md.                  *
 **************************************************************************/

#include <svd/modules/SVDTimeGroupingPlotter/SVDTimeGroupingPlotterModule.h>

// framework
#include <framework/logging/Logger.h>

// std
#include <limits>
#include <map>
#include <memory>

// root
#include <TF1.h>
#include <TLegend.h>
#include <TText.h>
#include <TLatex.h>
#include <TStyle.h>
#include <TROOT.h>
#include <TColor.h>

using namespace Belle2;

REG_MODULE(SVDTimeGroupingPlotter);


SVDTimeGroupingPlotterModule::SVDTimeGroupingPlotterModule() :
  Module()
{
  setDescription("Draws the SVD time-grouping histogram overlaid with the fitted per-group "
                 "Gaussians, one PDF page per event. Must run after SVDTimeGrouping.");

  addParam("SVDClusters", m_svdClustersName, "SVDCluster collection name.", std::string(""));
  addParam("outputFileName", m_outputFileName,
           "Path of the multi-page output PDF.", std::string("plots/svd_timegroups.pdf"));
  addParam("groupsToPlot", m_groupsToPlot,
           "Group ids to overlay. Empty list (default) overlays every reconstructed group.",
           std::vector<int>());
  addParam("maxPages", m_maxPages,
           "Stop after this many pages/events. <=0 means no limit.", int(0));

  // histogram-shape parameters -- keep the defaults identical to SVDTimeGrouping
  // so the redrawn distribution matches the one the algorithm fitted.
  addParam("tRangeLow", m_tRangeLow, "Histogram low edge [ns].", double(-160.));
  addParam("tRangeHigh", m_tRangeHigh, "Histogram high edge [ns].", double(160.));
  addParam("rebinningFactor", m_rebinningFactor, "Time bins per ns.", int(2));
  addParam("fillSigmaN", m_fillSigmaN,
           "Number of Gaussian sigmas used to smear each cluster into the histogram.", double(3.));
  addParam("useFullRange", m_useFullRange,
           "Draw the full [tRangeLow, tRangeHigh] window (e.g. +-160 ns) instead of shrinking "
           "the x-axis to the populated cluster-time span.", bool(true));

  // cluster-time resolutions, copied verbatim from SVDTimeGroupingModule
  // (indexing is [sensorType][isUCluster][clusterSize-1]).
  m_clsSigma[0][0] = {2.0417, 2.3606, 2.1915, 1.9810, 1.8042, 1.6205};
  m_clsSigma[0][1] = {3.5880, 3.4526, 2.9363, 2.6833, 2.5342, 2.2895};
  m_clsSigma[1][0] = {2.1069, 2.0530, 1.9895, 1.8720, 1.6453, 1.5905};
  m_clsSigma[1][1] = {3.3919, 2.2280, 2.1177, 2.0852, 1.9968, 1.9914};
  m_clsSigma[2][0] = {1.6863, 1.9920, 1.8498, 1.7737, 1.6320, 1.5629};
  m_clsSigma[2][1] = {3.2798, 3.2243, 2.9404, 2.7911, 2.6331, 2.5666};
}


void SVDTimeGroupingPlotterModule::initialize()
{
  m_svdClusters.isRequired(m_svdClustersName);
  m_eventMetaData.isRequired();

  gROOT->SetBatch(kTRUE);
  gStyle->SetOptStat(0);
  gStyle->SetTitleFontSize(0.038);   // smaller pad title
  gStyle->SetTitleX(0.5);            // centre it
  gStyle->SetTitleAlign(23);

  m_canvas = new TCanvas("svdTimeGroupCanvas", "SVD time grouping", 1200, 800);

  // open the multi-page PDF ("[" opens without emitting a page).
  m_canvas->Print((m_outputFileName + "[").c_str());
  m_pdfOpened = true;

  B2INFO("SVDTimeGroupingPlotter: writing per-event pages to " << m_outputFileName);
}


void SVDTimeGroupingPlotterModule::fillHistogram(TH1D& hist)
{
  const int totClusters = m_svdClusters.getEntries();

  // shrink the range to the populated cluster-time span, exactly as the
  // grouping module does (tmpRange[0] = max time, tmpRange[1] = min time).
  double tmpMax = std::numeric_limits<double>::quiet_NaN();
  double tmpMin = std::numeric_limits<double>::quiet_NaN();
  for (int ij = 0; ij < totClusters; ij++) {
    double clsTime = m_svdClusters[ij]->getClsTime();
    if (std::isnan(tmpMax) || clsTime > tmpMax) tmpMax = clsTime;
    if (std::isnan(tmpMin) || clsTime < tmpMin) tmpMin = clsTime;
  }

  double tRangeHigh = m_tRangeHigh;
  double tRangeLow  = m_tRangeLow;
  // The grouping module shrinks the fit range to the populated span; for display
  // we keep the full window by default so out-of-time groups are seen in context.
  if (!m_useFullRange && totClusters > 0) {
    if (tRangeHigh > tmpMax) tRangeHigh = tmpMax;
    if (tRangeLow  < tmpMin) tRangeLow  = tmpMin;
  }

  int nBin = int(tRangeHigh - tRangeLow);
  if (nBin < 1) nBin = 1;
  nBin *= m_rebinningFactor;
  if (nBin < 2) nBin = 2;

  hist = TH1D("h_clsTime", "h_clsTime", nBin, tRangeLow, tRangeHigh);
  hist.GetXaxis()->SetLimits(tRangeLow, tRangeHigh);

  for (int ij = 0; ij < totClusters; ij++) {
    double clsSize = m_svdClusters[ij]->getSize();
    bool   isUcls  = m_svdClusters[ij]->isUCluster();
    int    sType   = getSensorType(m_svdClusters[ij]->getSensorID());
    double gSigma  = (clsSize >= int(m_clsSigma[sType][isUcls].size()) ?
                      m_clsSigma[sType][isUcls].back() :
                      m_clsSigma[sType][isUcls][clsSize - 1]);
    double gCenter = m_svdClusters[ij]->getClsTime();

    addGausToHistogram(hist, 1., gCenter, gSigma, m_fillSigmaN);
  }
}


void SVDTimeGroupingPlotterModule::event()
{
  if (m_maxPages > 0 && m_pageCount >= m_maxPages) return;

  const int run = m_eventMetaData->getRun();
  const int evt = m_eventMetaData->getEvent();
  const int totClusters = m_svdClusters.getEntries();

  // rebuild the histogram the grouping algorithm fitted
  TH1D hist;
  fillHistogram(hist);

  // read back the per-group Gaussian parameters that SVDTimeGrouping stamped
  // onto the clusters. timeGroupId and timeGroupInfo run in parallel; leftover
  // (under/overflow/orphan) clusters carry an id but no info, so guard the index.
  std::map<int, std::tuple<float, float, float>> groupParams; // id -> (integral, center, sigma)
  std::map<int, int> groupCounts;                             // id -> number of clusters
  for (int ij = 0; ij < totClusters; ij++) {
    const std::vector<int>& ids = m_svdClusters[ij]->getTimeGroupId();
    const std::vector<std::tuple<float, float, float>>& infos = m_svdClusters[ij]->getTimeGroupInfo();
    for (size_t g = 0; g < ids.size(); g++) {
      int id = ids[g];
      groupCounts[id]++;
      if (g < infos.size()) groupParams[id] = infos[g];
    }
  }

  // decide which groups to overlay
  std::vector<int> groupsToDraw;
  if (m_groupsToPlot.empty()) {
    for (const auto& kv : groupParams) groupsToDraw.push_back(kv.first); // every fitted group
  } else {
    for (int id : m_groupsToPlot)
      if (groupParams.count(id)) groupsToDraw.push_back(id);
  }

  // draw
  m_canvas->cd();
  m_canvas->Clear();

  double ymax  = hist.GetMaximum();
  double yplot = (ymax > 0 ? ymax * 1.25 : 1.);
  hist.SetMaximum(yplot);
  hist.SetMinimum(0.);
  hist.SetLineColor(kBlack);
  hist.SetLineWidth(2);
  hist.SetTitle(Form("SVD time grouping - run %d, event %d  (%d clusters, %d groups);"
                     "cluster time [ns];Gaussian-weighted entries",
                     run, evt, totClusters, int(groupParams.size())));
  hist.DrawCopy("hist");

  // distinct colours cycled across the drawn groups
  static const int palette[] = {kRed + 1, kBlue + 1, kGreen + 2, kMagenta + 1, kOrange + 7,
                                kCyan + 2, kViolet - 1, kSpring + 4, kPink + 7, kAzure + 1
                               };
  const int nColours = sizeof(palette) / sizeof(palette[0]);

  // Full per-group legend (time, cluster count for every group), kept small so
  // that even ~20 groups fit without overlapping. Its height grows with the
  // number of entries; each peak is additionally tagged with its id (below).
  double legTop = 0.90;
  double legRow = 0.030;
  double legBot = legTop - (groupsToDraw.size() + 1) * legRow;
  if (legBot < 0.12) legBot = 0.12;

  TLegend leg(0.68, legBot, 0.90, legTop);
  leg.SetBorderSize(0);
  leg.SetFillStyle(0);
  leg.SetTextSize(0.016);
  leg.AddEntry(&hist, "cluster-time histogram", "l");

  // keep the TF1s / labels alive until after Print()
  std::vector<std::unique_ptr<TF1>> curves;
  std::vector<std::unique_ptr<TLatex>> labels;
  double xmin = hist.GetXaxis()->GetXmin();
  double xmax = hist.GetXaxis()->GetXmax();

  for (size_t k = 0; k < groupsToDraw.size(); k++) {
    int id = groupsToDraw[k];
    auto [integral, center, sigma] = groupParams[id];
    if (sigma <= 0.) continue;
    const int colour = palette[k % nColours];
    const bool isSignal = (id == 0); // group 0 is most signal-like after the grouping sort

    auto f = std::make_unique<TF1>(Form("group_%d", id), myGaus, xmin, xmax, 3);
    f->SetParameters(integral, center, sigma);
    f->SetNpx(500);
    f->SetLineColor(colour);
    f->SetLineWidth(2);
    f->Draw("same");

    leg.AddEntry(f.get(),
                 Form("group %d%s: t=%.0f ns, n=%d", id, isSignal ? " (signal)" : "",
                      center, groupCounts[id]), "l");

    // tag the group id just above the head of its Gaussian, in the group's colour
    double apex = integral / (sigma * 2.50662827); // peak height = integral / (sigma*sqrt(2pi))
    double ylab = apex + 0.015 * yplot;
    if (ylab > 0.97 * yplot) ylab = 0.97 * yplot;
    auto lab = std::make_unique<TLatex>(center, ylab, Form("%d", id));
    lab->SetTextColor(colour);
    lab->SetTextSize(0.016);
    lab->SetTextFont(62);  // bold, for legibility at small size
    lab->SetTextAlign(21); // horizontally centred over the peak, anchored at its bottom
    lab->Draw();

    curves.push_back(std::move(f));
    labels.push_back(std::move(lab));
  }

  leg.Draw();

  if (groupParams.empty()) {
    // grouping is skipped for events with <10 clusters -- say so on the page.
    TText* note = new TText(0.5, 0.5, "no time groups (grouping needs >=10 clusters)");
    note->SetNDC();
    note->SetTextAlign(22);
    note->SetTextColor(kGray + 2);
    note->Draw();
  }

  m_canvas->Print(m_outputFileName.c_str()); // emit one page
  m_pageCount++;
}


void SVDTimeGroupingPlotterModule::terminate()
{
  if (m_pdfOpened && m_canvas) {
    m_canvas->Print((m_outputFileName + "]").c_str()); // close the multi-page PDF
    B2INFO("SVDTimeGroupingPlotter: wrote " << m_pageCount << " page(s) to " << m_outputFileName);
  }
  delete m_canvas;
  m_canvas = nullptr;
}
