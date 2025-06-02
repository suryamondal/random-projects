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

void plot_stats(const char* teamName = "Mumbai Indians") {
  string nameOfTeam = teamName;

  gStyle->SetNumberContours(100);

  vector<string> files;
  set<string> battingPlayersSet;
  set<string> bowlingPlayersSet;

  // Maps to track position history
  map<string, vector<int>> battingPositions;
  map<string, vector<int>> bowlingPositions;

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
  vector<map<string, double>> bowlingData;

  for (const auto& filename : files) {
    ifstream f(filename);
    if (!f.is_open()) continue;

    json match;
    f >> match;
    f.close();

    const auto& innings = match["match"]["innings"];
    if (innings.empty()) continue;

    map<string, double> runMap;
    map<string, double> wicketMap;

    bool isPresent = false;
    for (int nIn : {0, 1}) {
      // Batting
      if (innings[nIn]["team_batting"] == nameOfTeam.c_str()) {
        int position = 0;
        for (const auto& player : innings[nIn]["batting"]) {
          ++position;
          string name = player["player"];
          double runs = player["runs"];
          double balls = player["balls"];
          if (runs > 0) {
            runMap[name] = runs * runs / balls;
            battingPlayersSet.insert(name);
            battingPositions[name].push_back(position);
          }
        }
        isPresent = true;
      }
      // Bowling
      if (innings[!nIn]["team_batting"] == nameOfTeam.c_str()) {
        int position = 0;
        for (const auto& player : innings[nIn]["bowling"]) {
          ++position;
          string name = player["player"];
          double wickets = player["wickets"];
          double rawOvers = player["overs"];
          int completedOvers = int(rawOvers);
          double balls = completedOvers * 6 + (rawOvers - completedOvers) * 10;
          double runs = player["runs_conceded"];
          double score = wickets * 30 + (balls - runs);
          wicketMap[name] = score;
          bowlingPlayersSet.insert(name);
          bowlingPositions[name].push_back(position);
        }
        isPresent = true;
      }
    }

    if (isPresent) {
      battingData.push_back(runMap);
      bowlingData.push_back(wicketMap);
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

  vector<pair<string, double>> bowlingAvgPositions;
  for (const auto& [name, positions] : bowlingPositions) {
    double avgPos = accumulate(positions.begin(), positions.end(), 0.0) / positions.size();
    bowlingAvgPositions.emplace_back(name, avgPos);
  }
  sort(bowlingAvgPositions.begin(), bowlingAvgPositions.end(), [](auto& a, auto& b) {
    return a.second < b.second;
  });

  // Assign sorted indices
  map<string, int> battingIndex, bowlingIndex;
  int idx = 1;
  for (const auto& [name, _] : battingAvgPositions) battingIndex[name] = idx++;
  idx = 1;
  for (const auto& [name, _] : bowlingAvgPositions) bowlingIndex[name] = idx++;

  int nMatches = battingData.size();
  int nBatPlayers = battingIndex.size();
  int nBowlPlayers = bowlingIndex.size();

  // Plot batting stats
  TCanvas *c1 = new TCanvas("c1", "Batting Stats", 1200, 600);
  c1->SetLeftMargin(0.1502504);
  gPad->SetGridy(1);
  gStyle->SetPaintTextFormat(".0f");

  TH2F *battingHist = new TH2F("batting", ("Runs " + nameOfTeam + "; Match Index;Player Name").c_str(), nMatches, 0.5, nMatches + 0.5, nBatPlayers, 0.5, nBatPlayers + 0.5);

  for (int i = 0; i < nMatches; ++i) {
    for (const auto& [name, runs] : battingData[i]) {
      if (runs > 1)
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
  c1->SaveAs(("plots/" + nameOfTeam + " Bat.pdf").c_str());

  // Plot bowling stats
  TCanvas *c2 = new TCanvas("c2", "Bowling Stats", 1200, 600);
  c2->SetLeftMargin(0.1502504);
  gPad->SetGridy(1);

  TH2F *bowlingHist = new TH2F("bowling", ("Bowling " + nameOfTeam + ";Match Index;Player Name").c_str(), nMatches, 0.5, nMatches + 0.5, nBowlPlayers, 0.5, nBowlPlayers + 0.5);

  for (int i = 0; i < nMatches; ++i) {
    for (const auto& [name, wkts] : bowlingData[i]) {
      bowlingHist->SetBinContent(i + 1, bowlingIndex[name], wkts > 0 ? wkts : 0.000001);
    }
  }

  for (const auto& [name, index] : bowlingIndex)
    bowlingHist->GetYaxis()->SetBinLabel(index, name.c_str());
  for (int i = 0; i < nMatches; ++i)
    bowlingHist->GetXaxis()->SetBinLabel(i + 1, TString::Format("%d", i + 1));

  c2->cd();
  gStyle->SetOptStat(0);
  bowlingHist->Draw("COLZ TEXT");
  bowlingHist->SetMaximum(100);
  c2->SaveAs(("plots/" + nameOfTeam + " Bowl.pdf").c_str());
}
