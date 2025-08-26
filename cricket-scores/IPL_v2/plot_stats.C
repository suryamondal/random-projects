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

void plot_stats(const vector<string>& playerNames) {

  set<string> skippedPlayers = {};
  set<string> playingSet(playerNames.begin(), playerNames.end());

  cout << "✅ Players in playingSet:" << endl;
  for (const auto& name : playingSet) cout << " - " << name << endl;

  gStyle->SetNumberContours(100);

  vector<string> files;
  map<string, int> playerIndex;

  // Maps to track position history
  map<string, vector<int>> scorePositions;

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

  vector<map<string, double>> scoreData;

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
        scorePositions[name].push_back(score);
      }
    }

    if (!runMap.empty()) {
      scoreData.push_back(runMap);
    }
  }

  // Compute average positions and sort
  vector<pair<string, double>> avgScores;
  for (const auto& [name, positions] : scorePositions) {
    double avgPos = accumulate(positions.begin(), positions.end(), 0.0) / positions.size();
    avgScores.emplace_back(name, avgPos);
  }
  sort(avgScores.begin(), avgScores.end(), [](auto& a, auto& b) {
    return a.second > b.second;
  });

  // Assign index based on sorted average
  int idx = 1;
  for (const auto& [name, _] : avgScores) {
    playerIndex[name] = idx++;
  }

  int nMatches = scoreData.size();
  int nPlayers = playerIndex.size();

  // Plot scores stats
  TCanvas *c1 = new TCanvas("c1", "Scores Stats", 1200, 600);
  c1->SetLeftMargin(0.1502504);
  gPad->SetGridy(1);
  gStyle->SetPaintTextFormat(".0f");

  TH2F *scoresHist = new TH2F("scores", "Player Scores ; Match Index; Player Name", nMatches, 0.5, nMatches + 0.5, nPlayers, 0.5, nPlayers + 0.5);

  for (int i = 0; i < nMatches; ++i) {
    for (const auto& [name, runs] : scoreData[i]) {
      if (runs > 1 && playerIndex.count(name))
        scoresHist->SetBinContent(i + 1, playerIndex[name], runs);
    }
  }

  for (const auto& [name, index] : playerIndex)
    scoresHist->GetYaxis()->SetBinLabel(index, name.c_str());
  for (int i = 0; i < nMatches; ++i)
    scoresHist->GetXaxis()->SetBinLabel(i + 1, TString::Format("%d", i + 1));

  c1->cd();
  gStyle->SetOptStat(0);
  scoresHist->Draw("COLZ TEXT");
  scoresHist->SetMinimum(0);
  // scoresHist->SetMaximum(100);

  gSystem->mkdir("plots", true);
  c1->SaveAs("plots/Scores.pdf");

}
