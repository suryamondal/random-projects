#include <TCanvas.h>
#include <TH2F.h>
#include <TStyle.h>
#include <TSystemDirectory.h>
#include <TSystemFile.h>
#include <TList.h>
#include <TString.h>

#include <fstream>
#include <iostream>
#include <vector>
#include <map>
#include <set>
#include <numeric>
#include <algorithm>

#include <nlohmann/json.hpp>

using json = nlohmann::json;
using namespace std;

void plot_stats(const vector<string> playerNames) {

  set<string> skippedPlayers = {};
  set<string> playingSet = playerNames;

  gStyle->SetNumberContours(100);

  vector<string> files;
  set<string> battingPlayersSet;
  map<string, int> battingIndex;

  // Maps to track position history
  map<string, vector<int>> battingPositions;

  // Scan directory for JSON files
  TSystemDirectory dir("data", "./data");
  TList *filesList = dir.GetListOfFiles();
  if (!filesList) {
    cerr << "No files found in ./data" << endl;
    return;
  }

  // Extract and sort files
  TIter next(filesList);
  TSystemFile *file;
  while ((file = (TSystemFile*)next())) {
    TString fname = file->GetName();
    if (!file->IsDirectory() && fname.EndsWith(".json")) {
      files.push_back("data/" + string(fname));
    }
  }
  sort(files.begin(), files.end());

  vector<map<string, double>> battingData;

  for (const auto& filename : files) {
    ifstream f(filename);
    if (!f.is_open()) continue;

    json match;
    f >> match;
    f.close();

    if (!match.contains("version") || match["version"] != "2") continue;
    if (!match.contains("match") || !match["match"].contains("stat")) continue;

    const auto& innings = match["match"]["stat"];
    map<string, double> runMap;

    for (const auto& player : innings) {
      if (!player.contains("player") || !player.contains("score")) continue;
      string name = player["player"];
      if (skippedPlayers.count(name) || !playingSet.count(name)) continue;

      double score = player["score"];
      if (score > 0) {
        runMap[name] = score;
        battingPlayersSet.insert(name);
        battingPositions[name].push_back(score);
      }
    }

    if (!runMap.empty()) {
      battingData.push_back(runMap);
    }
  }

  // Compute average positions and sort
  vector<pair<string, double>> battingAvgPositions;
  for (const auto& [name, positions] : battingPositions) {
    double avgPos = accumulate(positions.begin(), positions.end(), 0.0) / positions.size();
    battingAvgPositions.emplace_back(name, avgPos);
  }
  sort(battingAvgPositions.begin(), battingAvgPositions.end(), [](auto& a, auto& b) {
    return a.second < b.second;
  });

  // Assign index based on sorted average
  int idx = 1;
  for (const auto& [name, _] : battingAvgPositions) {
    battingIndex[name] = idx++;
  }

  int nMatches = battingData.size();
  int nBatPlayers = battingIndex.size();

  // Plot batting stats
  TCanvas *c1 = new TCanvas("c1", "Batting Stats", 1200, 600);
  c1->SetLeftMargin(0.1502504);
  gPad->SetGridy(1);
  gStyle->SetPaintTextFormat(".0f");

  TH2F *battingHist = new TH2F("batting", "Runs ; Match Index;Player Name", nMatches, 0.5, nMatches + 0.5, nBatPlayers, 0.5, nBatPlayers + 0.5);

  for (int i = 0; i < nMatches; ++i) {
    for (const auto& [name, runs] : battingData[i]) {
      if (runs > 1 && battingIndex.count(name))
        battingHist->SetBinContent(i + 1, battingIndex[name], runs);
    }
  }

  for (const auto& [name, index] : battingIndex)
    battingHist->GetYaxis()->SetBinLabel(index, name.c_str());
  for (int i = 0; i < nMatches; ++i)
    battingHist->GetXaxis()->SetBinLabel(i + 1, TString::Format("%d", i + 1));

  c1->cd();
  gStyle->SetOptStat(0);
  battingHist->Draw("COLZ TEXT");
  battingHist->SetMinimum(0);
  battingHist->SetMaximum(100);

  gSystem->mkdir("plots", true);
  c1->SaveAs("plots/Bat.pdf");

}
