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

  // gStyle->SetOptStat(0);
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

    bool isPresent = false;
    for (int nIn : {0, 1}) {
      // Batting
      if (innings[nIn]["team_batting"] == nameOfTeam.c_str()) {
        for (const auto& player : innings[nIn]["batting"]) {
          string name = player["player"];
          double runs = player["runs"];
          double balls = player["balls"];
          if (runs > 0) {
            runMap[name] = runs * runs / balls;
            battingPlayersSet.insert(name);
          }
        }
        isPresent = true;
      }
      // Bowling
      if (innings[!nIn]["team_batting"] == nameOfTeam.c_str()) {
        for (const auto& player : innings[nIn]["bowling"]) {
          string name = player["player"];
          double wickets = player["wickets"];
          double rawOvers = player["overs"];
          int completedOvers = int(rawOvers);
          double balls = completedOvers * 6 + (rawOvers - completedOvers) * 10;
          double runs = player["runs_conceded"];
          double score = wickets * 30 + (balls - runs);
          // std::cout << score << std::endl;
          // if (score > 0) {
          wicketMap[name] = score;
          bowlingPlayersSet.insert(name);
          // }
        }
        isPresent = true;
      }
    }
    if (isPresent) {
      // if (runMap.size())
      battingData.push_back(runMap);
      // if (wicketMap.size())
      bowlingData.push_back(wicketMap);
    }
  }

  // Assign indices to players
  map<string, int> battingIndex;
  map<string, int> bowlingIndex;
  int idx = 1;
  for (const auto& name : battingPlayersSet) battingIndex[name] = idx++;
  idx = 1;
  for (const auto& name : bowlingPlayersSet) bowlingIndex[name] = idx++;

  // Unified player set and index for combined stats
  set<string> allPlayersSet = battingPlayersSet;
  allPlayersSet.insert(bowlingPlayersSet.begin(), bowlingPlayersSet.end());
  map<string, int> playerIndex;
  idx = 1;
  for (const auto& name : allPlayersSet) playerIndex[name] = idx++;
  int nAllPlayers = playerIndex.size();

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
  TH1F *battingModes = new TH1F("batting_modes", ("Batting Modes " + nameOfTeam + ";Batting Score;Count").c_str(), 50, 0, 100);

  for (int i = 0; i < nMatches; ++i) {
    for (const auto& [name, runs] : battingData[i]) {
      if (runs > 1)
        battingHist->SetBinContent(i + 1, battingIndex[name], runs);
      battingModes->Fill(runs);
    }
  }

  for (const auto& [name, idx] : battingIndex)
    battingHist->GetYaxis()->SetBinLabel(idx, name.c_str());
  for (int i = 0; i < nMatches; ++i)
    battingHist->GetXaxis()->SetBinLabel(i + 1, TString::Format("%d", i + 1));

  // ofstream batCsv(("plots/" + nameOfTeam + " Batting.csv").c_str());
  // batCsv << "Match";
  // for (const auto& [name, idx] : battingIndex)
  //   batCsv << "," << name;
  // batCsv << "\n";
  // for (int i = 1; i <= nMatches; ++i) {
  //   batCsv << i;
  //   for (const auto& [name, idx] : battingIndex) {
  //     batCsv << "," << battingHist->GetBinContent(i, idx);
  //   }
  //   batCsv << "\n";
  // }
  // batCsv.close();


  c1->cd();
  gStyle->SetOptStat(0);
  // battingHist->SetMarkerFormat("%.1f");
  battingHist->Draw("COLZ TEXT");
  battingHist->SetMinimum(0);
  battingHist->SetMaximum(100);
  c1->SaveAs(("plots/" + nameOfTeam + " Bat.pdf").c_str());

  TCanvas *c3 = new TCanvas("c3", "Batting Modes", 1200, 600);
  gStyle->SetOptStat("uo");
  c3->SetLeftMargin(0.1502504);
  battingModes->Draw("HIST");
  c3->SaveAs(("plots/" + nameOfTeam + " Bat Modes.pdf").c_str());

  TCanvas *c2 = new TCanvas("c2", "Bowling Stats", 1200, 600);
  c2->SetLeftMargin(0.1502504);
  // gPad->SetGridx(1);
  gPad->SetGridy(1);
  // gStyle->SetPaintTextFormat(".1f");

  TH2F *bowlingHist = new TH2F("bowling", ("Bowling " + nameOfTeam + ";Match Index;Player Name").c_str(), nMatches, 0.5, nMatches + 0.5, nBowlPlayers, 0.5, nBowlPlayers + 0.5);
  TH1F *bowlingModes = new TH1F("bowling_modes", ("Bowling Modes " + nameOfTeam + ";Bowling Score;Count").c_str(), 70, -40, 100);

  for (int i = 0; i < nMatches; ++i) {
    for (const auto& [name, wkts] : bowlingData[i]) {
      bowlingHist->SetBinContent(i + 1, bowlingIndex[name], wkts > 0 ? wkts : 0.0000001);
      bowlingModes->Fill(wkts);
    }
  }

  for (const auto& [name, idx] : bowlingIndex)
    bowlingHist->GetYaxis()->SetBinLabel(idx, name.c_str());
  for (int i = 0; i < nMatches; ++i)
    bowlingHist->GetXaxis()->SetBinLabel(i + 1, TString::Format("%d", i + 1));

  // ofstream bowlCsv(("plots/" + nameOfTeam + " Bowling.csv").c_str());
  // bowlCsv << "Match";
  // for (const auto& [name, idx] : bowlingIndex)
  //   bowlCsv << "," << name;
  // bowlCsv << "\n";
  // for (int i = 1; i <= nMatches; ++i) {
  //   bowlCsv << i;
  //   for (const auto& [name, idx] : bowlingIndex) {
  //     bowlCsv << "," << bowlingHist->GetBinContent(i, idx);
  //   }
  //   bowlCsv << "\n";
  // }
  // bowlCsv.close();


  c2->cd();
  gStyle->SetOptStat(0);
  // bowlingHist->SetMarkerFormat("%.1f");
  bowlingHist->Draw("COLZ TEXT");
  // bowlingHist->SetMinimum(-1);
  bowlingHist->SetMaximum(100);
  c2->SaveAs(("plots/" + nameOfTeam + " Bowl.pdf").c_str());

  TCanvas *c4 = new TCanvas("c4", "Bowling Modes", 1200, 600);
  gStyle->SetOptStat("uo");
  c4->SetLeftMargin(0.1502504);
  bowlingModes->Draw("HIST");
  c4->SaveAs(("plots/" + nameOfTeam + " Bowl Modes.pdf").c_str());

  // Combined stats: TH2F for player vs player total contributions
  TH2F *combinedHist = new TH2F("combined", ("Combined Contribution " + nameOfTeam).c_str(),
                                nAllPlayers, 0.5, nAllPlayers + 0.5,
                                nAllPlayers, 0.5, nAllPlayers + 0.5);
  for (int i = 0; i < nMatches; ++i) {
    map<string, double> scoreMap;
    // Aggregate scores from batting and bowling
    for (const auto& [name, val] : battingData[i])
      scoreMap[name] += val;
    for (const auto& [name, val] : bowlingData[i])
      scoreMap[name] += val;
    // Fill matrix with asymmetric rule
    for (const auto& [p1, score1] : scoreMap) {
      int idx1 = playerIndex[p1];
      for (const auto& [p2, score2] : scoreMap) {
        int idx2 = playerIndex[p2];
        if (idx1 == idx2) continue; // Skip diagonal
        // combinedHist->Fill(idx1, idx2, 2 * score1 * score2 / (score1 + score2));
        combinedHist->Fill(idx1, idx2, score1 + score2);
        // combinedHist->Fill(idx1, idx2, TMath::Sqrt(score1 * score2));
      }
    }
  }
  combinedHist->Scale(1./nMatches);
  // Label axes
  for (const auto& [name, idx] : playerIndex) {
    combinedHist->GetXaxis()->SetBinLabel(idx, name.c_str());
    combinedHist->GetYaxis()->SetBinLabel(idx, name.c_str());
  }
  // Draw canvas
  TCanvas *c5 = new TCanvas("c5", "Combined Player Synergy", 1200, 1200);
  c5->SetLeftMargin(0.20);
  c5->SetBottomMargin(0.20);
  gStyle->SetOptStat(0);
  gPad->SetGridx(1);
  gPad->SetGridy(1);
  combinedHist->GetXaxis()->SetLabelSize(0.025);
  combinedHist->GetYaxis()->SetLabelSize(0.025);
  combinedHist->GetZaxis()->SetLabelSize(0.015);
  combinedHist->SetMarkerSize(0.5);
  combinedHist->SetMinimum(-10);
  combinedHist->SetMaximum(+150);
  combinedHist->Draw("COLZ TEXT");
  c5->SaveAs(("plots/" + nameOfTeam + " - Synergy.pdf").c_str());

}
