/**************************************************************************
 * basf2 (Belle II Analysis Software Framework)                           *
 * Author: The Belle II Collaboration                                     *
 *                                                                        *
 * See git log for contributors and copyright holders.                    *
 * This file is licensed under LGPL-3.0, see LICENSE.md.                  *
 **************************************************************************/

#pragma once

// framework
#include <framework/core/Module.h>
#include <framework/datastore/StoreArray.h>
#include <framework/datastore/StoreObjPtr.h>
#include <framework/dataobjects/EventMetaData.h>

// svd
#include <svd/dataobjects/SVDCluster.h>
// reuse the peak-shaping helpers (addGausToHistogram, getSensorType, myGaus, GroupInfo)
// from the production grouping module so the redrawn histogram matches it bin-for-bin.
#include <svd/modules/svdTimeGrouping/SVDTimeGroupingModule.h>

// std
#include <string>
#include <vector>

// root
#include <TH1D.h>
#include <TCanvas.h>

namespace Belle2 {

  /**
   * Draws, one PDF page per event, the SVD time-grouping histogram overlaid with
   * the fitted per-group Gaussians.
   *
   * Runs *after* SVDTimeGrouping. It reads back the group parameters that the
   * grouping module stamped onto every SVDCluster (integral, center, sigma) and
   * rebuilds the same cluster-time histogram the algorithm fitted, so the picture
   * shows exactly what the grouping saw. Signal/background groups are drawn as
   * coloured Gaussian curves on top of the black cluster-time distribution.
   *
   * By default every reconstructed group is drawn; set `groupsToPlot` to a list
   * of group ids to overlay only selected (e.g. signal) groups.
   */
  class SVDTimeGroupingPlotterModule : public Module {

  public:

    /** Constructor: declares the module parameters. */
    SVDTimeGroupingPlotterModule();

    /** Require the cluster StoreArray, open the multi-page PDF. */
    virtual void initialize() override;

    /** Draw one page for the current event. */
    virtual void event() override;

    /** Close the multi-page PDF. */
    virtual void terminate() override;

  private:

    /** Rebuild the grouping histogram from the current event's clusters.
     *
     * Replicates SVDTimeGroupingModule::createAndFillHistorgram: the range is
     * shrunk to the populated cluster-time span and each cluster is smeared with
     * its hard-coded time resolution.
     */
    void fillHistogram(TH1D& hist);

    // parameters
    std::string m_svdClustersName;   /**< SVDCluster collection name. */
    std::string m_outputFileName;    /**< Path of the multi-page output PDF. */
    std::vector<int> m_groupsToPlot; /**< Group ids to overlay; empty means all reconstructed groups. */
    double m_tRangeLow;              /**< Histogram low edge [ns] (matches grouping tRangeLow). */
    double m_tRangeHigh;             /**< Histogram high edge [ns] (matches grouping tRangeHigh). */
    int    m_rebinningFactor;        /**< Bins per ns (matches grouping rebinningFactor). */
    double m_fillSigmaN;             /**< Gaussian fill half-width in sigmas (matches grouping fillSigmaN). */
    bool   m_useFullRange;           /**< Draw the full [tRangeLow,tRangeHigh] window instead of shrinking to the populated span. */
    int    m_maxPages;               /**< Stop after this many pages; <=0 means no limit. */

    // data members
    StoreArray<SVDCluster>    m_svdClusters;   /**< the SVD clusters, already grouped. */
    StoreObjPtr<EventMetaData> m_eventMetaData; /**< for run/event numbers in page titles. */

    TCanvas* m_canvas = nullptr;  /**< canvas reused for every page. */
    int  m_pageCount = 0;         /**< number of pages written so far. */
    bool m_pdfOpened = false;     /**< whether the multi-page PDF has been opened. */

    /** Hard-coded cluster-time resolutions [sensorType][isU][clsSize-1], in ns.
     *  Copied from SVDTimeGroupingModule so the redrawn histogram is identical
     *  when grouping runs with useParamFromDB=False (its compiled defaults). */
    std::vector<double> m_clsSigma[3][2];
  };

} // namespace Belle2
