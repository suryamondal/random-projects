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

// mdst
#include <mdst/dataobjects/MCParticle.h>

// std
#include <algorithm>
#include <limits>
#include <map>
#include <memory>
#include <string>

// root
#include <TF1.h>
#include <TLegend.h>
#include <TText.h>
#include <TLatex.h>
#include <TLine.h>
#include <TStyle.h>
#include <TPad.h>
#include <TVirtualPad.h>
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
  gStyle->SetPaperSize(29.7, 21.0);  // A4 landscape, so the printed page matches the wide canvas

  // two columns: left = raw cluster-time histogram, right = Gaussian-weighted.
  // Aspect ~A4 landscape (1.41:1) so the two pads fill the printed PDF page.
  m_canvas = new TCanvas("svdTimeGroupCanvas", "SVD time grouping", 1700, 1200);

  // Explicit pads spanning the full canvas height, with our own margins, so the
  // plots fill the page edge-to-edge (no Divide() whitespace).
  m_canvas->cd();
  m_padL = new TPad("padL", "", 0.00, 0.00, 0.50, 1.00);
  m_padR = new TPad("padR", "", 0.50, 0.00, 1.00, 1.00);
  for (TPad* p : {m_padL, m_padR}) {
    p->SetLeftMargin(0.15);   // room for the y-axis title + labels (was clipping the page edge)
    p->SetRightMargin(0.03);
    p->SetTopMargin(0.09);
    p->SetBottomMargin(0.10);
    p->Draw();
  }

  // open the multi-page PDF ("[" opens without emitting a page).
  m_canvas->Print((m_outputFileName + "[").c_str());
  m_pdfOpened = true;

  B2INFO("SVDTimeGroupingPlotter: writing per-event pages to " << m_outputFileName);
}


void SVDTimeGroupingPlotterModule::fillHistogram(TH1D& hist, bool gaussFill)
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

  const char* name = gaussFill ? "h_weighted" : "h_raw";
  hist = TH1D(name, name, nBin, tRangeLow, tRangeHigh);
  hist.GetXaxis()->SetLimits(tRangeLow, tRangeHigh);

  for (int ij = 0; ij < totClusters; ij++) {
    double gCenter = m_svdClusters[ij]->getClsTime();

    if (!gaussFill) {
      // raw: one count per cluster at its cluster time, no smearing
      hist.Fill(gCenter);
      continue;
    }

    // Gaussian-weighted: smear each cluster with its hard-coded time resolution
    double clsSize = m_svdClusters[ij]->getSize();
    bool   isUcls  = m_svdClusters[ij]->isUCluster();
    int    sType   = getSensorType(m_svdClusters[ij]->getSensorID());
    double gSigma  = (clsSize >= int(m_clsSigma[sType][isUcls].size()) ?
                      m_clsSigma[sType][isUcls].back() :
                      m_clsSigma[sType][isUcls][clsSize - 1]);

    addGausToHistogram(hist, 1., gCenter, gSigma, m_fillSigmaN);
  }
}


void SVDTimeGroupingPlotterModule::event()
{
  if (m_maxPages > 0 && m_pageCount >= m_maxPages) return;

  const int run = m_eventMetaData->getRun();
  const int evt = m_eventMetaData->getEvent();
  const int totClusters = m_svdClusters.getEntries();

  // build both histograms; identical binning, they differ only in the fill:
  //   weighted -> the distribution the grouping algorithm fits (right pad)
  //   raw      -> one count per cluster, no smearing        (left pad)
  TH1D histWeighted, histRaw;
  fillHistogram(histWeighted, /*gaussFill=*/true);
  fillHistogram(histRaw,      /*gaussFill=*/false);

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

  // Identify the true signal clusters from MC truth and find which group wins
  // them. A cluster is signal if it is related to an MCParticle; beam-background
  // overlay clusters carry no MC relation. The signal group -- NOT assumed to be
  // group 0 -- is the fitted group holding the most signal clusters. The mean
  // time of the signal clusters is marked with a dotted line.
  int    signalGroupId  = -999; // group tagged as signal (none by default)
  double signalMeanTime = 0.;
  bool   haveSignal     = false;
  {
    std::map<int, int> signalPerGroup;
    double sumT = 0.;
    int    nSig = 0;
    for (int ij = 0; ij < totClusters; ij++) {
      if (!m_svdClusters[ij]->getRelatedTo<MCParticle>()) continue; // background overlay
      nSig++;
      sumT += m_svdClusters[ij]->getClsTime();
      for (int id : m_svdClusters[ij]->getTimeGroupId()) signalPerGroup[id]++;
    }
    if (nSig > 0) { signalMeanTime = sumT / nSig; haveSignal = true; }
    int best = 0;
    for (const auto& kv : signalPerGroup)
      if (groupParams.count(kv.first) && kv.second > best) { best = kv.second; signalGroupId = kv.first; }
  }

  // distinct colours cycled across the drawn groups
  static const int palette[] = {kRed + 1, kBlue + 1, kGreen + 2, kMagenta + 1, kOrange + 7,
                                kCyan + 2, kViolet - 1, kSpring + 4, kPink + 7, kAzure + 1
                               };
  const int nColours = sizeof(palette) / sizeof(palette[0]);

  const double binWidth = 1.0 / std::max(1, m_rebinningFactor); // ns per bin (0.5 by default)

  // objects that must stay alive until Print() renders the whole canvas
  std::vector<std::unique_ptr<TF1>>     curves;
  std::vector<std::unique_ptr<TLatex>>  labels;
  std::vector<std::unique_ptr<TLegend>> legends;
  std::vector<std::unique_ptr<TText>>   notes;
  std::vector<std::unique_ptr<TLine>>   lines;

  // draw a single pad: base histogram + the per-group Gaussian overlays. gScale
  // rescales each group's stored integral to the pad's y-units: 1 for the
  // Gaussian-weighted pad, binWidth for the raw count histogram (its bins hold
  // counts, so a group of n clusters has area n*binWidth in x).
  auto drawPad = [&](TPad * pad, TH1D & h, double gScale, const char* subtitle, const char* ytitle) {
    pad->cd();
    pad->Clear();

    double ymax  = h.GetMaximum();
    double yplot = (ymax > 0 ? ymax * 1.25 : 1.);
    h.SetMaximum(yplot);
    h.SetMinimum(0.);
    h.SetLineColor(kBlack);
    h.SetLineWidth(2);
    h.SetTitle(Form("run %d, event %d - %s  (%d clusters, %d groups);cluster time [ns];%s",
                    run, evt, subtitle, totClusters, int(groupParams.size()), ytitle));
    h.GetYaxis()->SetTitleOffset(1.15); // keep the title inside the pad margin
    h.GetYaxis()->SetTitleSize(0.040);
    h.GetYaxis()->SetLabelSize(0.035);
    h.DrawCopy("hist");

    // full per-group legend, kept small so ~20 groups fit; box grows with entries
    // (+2 rows for the histogram and signal-mean entries)
    double legTop = 0.90, legRow = 0.030;
    double legBot = legTop - (groupsToDraw.size() + 2) * legRow;
    if (legBot < 0.12) legBot = 0.12;
    auto leg = std::make_unique<TLegend>(0.66, legBot, 0.90, legTop);
    leg->SetBorderSize(0);
    leg->SetFillStyle(0);
    leg->SetTextSize(0.016);
    leg->AddEntry(&h, "cluster-time histogram", "l");

    double xmin = h.GetXaxis()->GetXmin();
    double xmax = h.GetXaxis()->GetXmax();

    for (size_t k = 0; k < groupsToDraw.size(); k++) {
      int id = groupsToDraw[k];
      auto [integral, center, sigma] = groupParams[id];
      if (sigma <= 0.) continue;
      const int colour = palette[k % nColours];
      const bool isSignal = (id == signalGroupId); // the group that won the true signal clusters
      const double scaledIntegral = integral * gScale;

      auto f = std::make_unique<TF1>(Form("g_%s_%d", h.GetName(), id), myGaus, xmin, xmax, 3);
      f->SetParameters(scaledIntegral, center, sigma);
      f->SetNpx(500);
      f->SetLineColor(colour);
      f->SetLineWidth(2);
      f->Draw("same");

      leg->AddEntry(f.get(),
                    Form("group %d%s: t=%.0f ns, n=%d", id, isSignal ? " (signal)" : "",
                         center, groupCounts[id]), "l");

      // tag the group id just above the head of its Gaussian, in the group's colour
      double apex = scaledIntegral / (sigma * 2.50662827); // peak height = integral / (sigma*sqrt(2pi))
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

    // dotted vertical line at the mean time of the true signal clusters
    if (haveSignal) {
      auto line = std::make_unique<TLine>(signalMeanTime, 0., signalMeanTime, yplot);
      line->SetLineStyle(3);   // dotted
      line->SetLineWidth(2);
      line->SetLineColor(kBlack);
      line->Draw();
      leg->AddEntry(line.get(), Form("signal mean: t=%.0f ns", signalMeanTime), "l");
      lines.push_back(std::move(line));
    }

    leg->Draw();
    legends.push_back(std::move(leg));

    if (groupParams.empty()) {
      // grouping is skipped for events with <10 clusters -- say so on the pad.
      auto note = std::make_unique<TText>(0.5, 0.5, "no time groups (grouping needs >=10 clusters)");
      note->SetNDC();
      note->SetTextAlign(22);
      note->SetTextColor(kGray + 2);
      note->Draw();
      notes.push_back(std::move(note));
    }
  };

  const std::string rawSub   = Form("raw cluster time (%.2g ns bins)", binWidth);
  const std::string rawYaxis = Form("clusters / %.2g ns", binWidth);

  drawPad(m_padL, histRaw, binWidth, rawSub.c_str(), rawYaxis.c_str());
  drawPad(m_padR, histWeighted, 1.0, "Gaussian-weighted (fitted)", "Gaussian-weighted entries");

  m_canvas->cd();
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
