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
#include <algorithm>

#include <nlohmann/json.hpp>

using json = nlohmann::json;
using namespace std;

void plot_stats(const char* teamName = "Mumbai Indians") {
  string nameOfTeam = teamName;

  gStyle->SetOptStat(0);
  // gStyle->SetPalette(1);
  gStyle->SetNumberContours(100);

  vector<string> files;
  set<string> battingPlayersSet;
  set<string> bowlingPlayersSet;

  // Scan directory for JSON files
  TSystemDirectory dir("data", "./data");
  TList *filesList = dir.GetListOfFiles();
  if (!filesList) {
    cerr << "No files found in ./data" << endl;
    return;
  }

  // Extract files
  TIter next(filesList);
  TSystemFile *file;
  while ((file = (TSystemFile*)next())) {
    TString fname = file->GetName();
    if (!file->IsDirectory() && fname.EndsWith(".json")) {
      files.push_back("data/" + string(fname));
    }
  }

  // Sort files to get matches in order
  sort(files.begin(), files.end());

  vector<map<string, double>> battingData; // matchIndex -> {player -> runs}
  vector<map<string, double>> bowlingData; // matchIndex -> {player -> wickets}

  // Load and process each file
  for (const auto& filename : files) {

    std::cout << filename << std::endl;

    ifstream f(filename);
    if (!f.is_open()) continue;

    json match;
    f >> match;
    f.close();

    const auto& innings = match["match"]["innings"];

    if (innings.empty()) continue;

    map<string, double> runMap;
    map<string, double> wicketMap;

    for (int nIn : {0, 1}) {
      // Batting
      if (innings[nIn]["team_batting"] == nameOfTeam.c_str())
        for (const auto& player : innings[nIn]["batting"]) {
          string name = player["player"];
          double runs = player["runs"];
          double balls = player["balls"];
          if (runs > 0) {
            runMap[name] = runs * runs / balls;
            battingPlayersSet.insert(name);
          }
        }
      // Bowling
      if (innings[!nIn]["team_batting"] == nameOfTeam.c_str())
        for (const auto& player : innings[nIn]["bowling"]) {
          string name = player["player"];
          double wickets = player["wickets"];
          double rawOvers = player["overs"];
          int completedOvers = int(rawOvers);
          double balls = completedOvers * 6 + (rawOvers - completedOvers) * 10;
          double runs = player["runs_conceded"];
          if (wickets > 0) {
            wicketMap[name] = wickets * balls / runs;
            bowlingPlayersSet.insert(name);
          }
        }
    }
    if (runMap.size())
      battingData.push_back(runMap);
    if (wicketMap.size())
      bowlingData.push_back(wicketMap);
  }

  // Assign indices to players
  map<string, int> battingIndex;
  map<string, int> bowlingIndex;
  int idx = 1;
  for (const auto& name : battingPlayersSet) battingIndex[name] = idx++;
  idx = 1;
  for (const auto& name : bowlingPlayersSet) bowlingIndex[name] = idx++;

  int nMatches = battingData.size();
  int nBatPlayers = battingIndex.size();
  int nBowlPlayers = bowlingIndex.size();

  // Plotting
  TCanvas *c1 = new TCanvas("c1", "Batting Stats", 1200, 600);
  c1->SetLeftMargin(0.1502504);
  // gPad->SetGridx(1);
  gPad->SetGridy(1);
  gStyle->SetPaintTextFormat(".0f");

  TH2F *battingHist = new TH2F("batting", ("Runs " + nameOfTeam + "; Match Index;Player Name").c_str(), nMatches, 0.5, nMatches + 0.5, nBatPlayers, 0.5, nBatPlayers + 0.5);

  for (int i = 0; i < nMatches; ++i) {
    for (const auto& [name, runs] : battingData[i]) {
      if (runs > 1)
        battingHist->SetBinContent(i + 1, battingIndex[name], runs);
    }
  }

  for (const auto& [name, idx] : battingIndex)
    battingHist->GetYaxis()->SetBinLabel(idx, name.c_str());
  for (int i = 0; i < nMatches; ++i)
    battingHist->GetXaxis()->SetBinLabel(i + 1, TString::Format("%d", i + 1));

  // battingHist->SetMarkerFormat("%.1f");
  battingHist->Draw("COLZ TEXT");
  battingHist->SetMinimum(0);
  battingHist->SetMaximum(100);
  c1->SaveAs(("plots/" + nameOfTeam + " Bat.pdf").c_str());

  TCanvas *c2 = new TCanvas("c2", "Bowling Stats", 1200, 600);
  c2->SetLeftMargin(0.1502504);
  // gPad->SetGridx(1);
  gPad->SetGridy(1);
  gStyle->SetPaintTextFormat(".1f");

  TH2F *bowlingHist = new TH2F("bowling", ("Wickets " + nameOfTeam + ";Match Index;Player Name").c_str(), nMatches, 0.5, nMatches + 0.5, nBowlPlayers, 0.5, nBowlPlayers + 0.5);

  for (int i = 0; i < nMatches; ++i) {
    for (const auto& [name, wkts] : bowlingData[i]) {
      if (wkts > 0)
        bowlingHist->SetBinContent(i + 1, bowlingIndex[name], wkts);
    }
  }

  for (const auto& [name, idx] : bowlingIndex)
    bowlingHist->GetYaxis()->SetBinLabel(idx, name.c_str());
  for (int i = 0; i < nMatches; ++i)
    bowlingHist->GetXaxis()->SetBinLabel(i + 1, TString::Format("%d", i + 1));

  // bowlingHist->SetMarkerFormat("%.1f");
  bowlingHist->Draw("COLZ TEXT");
  bowlingHist->SetMinimum(0);
  bowlingHist->SetMaximum(5);
  c2->SaveAs(("plots/" + nameOfTeam + " Bowl.pdf").c_str());

  // Interactive canvas will stay open
}
