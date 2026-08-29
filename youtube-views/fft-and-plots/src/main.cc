
#include "TPad.h"
#include "TAxis.h"
#include "TCanvas.h"
#include "TGraph.h"
#include "TMath.h"
#include "TDatime.h"

#include "utils.h"
#include "fft.h"

#include <string>
#include <fstream>


const double timeInterval = 5.0 * 60.0 / (24.0 * 3600.0);

int main(int argc, char *argv[]) {

  if (argc < 2) {
    std::cerr << "Use: ./executable file-tag" << std::endl;
    return -1;
  }

  std::string fileTag = argv[1];
  
  std::string fileName = "data/" + fileTag + "_views.csv";
  std::ifstream file(fileName.c_str());
  if (!file.is_open()) {
    std::cerr << "Cannot open file! " << fileName << std::endl;
    return -1;
  }

  std::string line;
  std::getline(file, line); // skip header

  std::vector<double> times;
  std::vector<double> views;

  while (std::getline(file, line)) {
    std::stringstream ss(line);
    std::string timestamp, tag, views_str;

    std::getline(ss, timestamp, ',');
    std::getline(ss, tag, ',');
    std::getline(ss, views_str, ',');

    int year, month, day, hour, min, sec;
    sscanf(timestamp.c_str(), "%d-%d-%d %d:%d:%d",
           &year, &month, &day, &hour, &min, &sec);
    TDatime dt(year, month, day, hour, min, sec);
    double time_val = dt.Convert();  // Convert to seconds since epoch

    times.push_back(time_val);
    views.push_back(std::stod(views_str));
  }

  const Long64_t inputDataPt = times.size();
  const double tPD = (times.back() - times.front()) / (24.0 * 3600.0);
  const Long64_t maxDesiredPt = tPD / timeInterval;

  std::vector<double> pos0, amp0;	// Input Data Vector before Padding
  pos0.clear(); pos0.reserve(inputDataPt);
  amp0.clear(); amp0.reserve(inputDataPt);
  /** Generating Data Points */
  for(int ij=0;ij<inputDataPt;ij++) {
    pos0.push_back(times[ij] / (24.0 * 3600.0));
    amp0.push_back(views[ij]);
  }

  std::cout << " Input Data Size " << inputDataPt << std::endl;
  std::cout << " Input Data Length " << tPD << std::endl;

  int pFactor = utils::findExponent(maxDesiredPt, 2);
  const Long64_t nn = std::pow(2, pFactor); // Number for Padding
  std::cout << " Size of FFT Input " << nn << std::endl;

  std::vector<double> outPos,outAmp; // Vector for Padded Data
  outPos.clear(); outPos.reserve(nn);
  outAmp.clear(); outAmp.reserve(nn);

  utils::padData(pos0, amp0, outPos, outAmp, nn);

  fft::dft::CNArray data_C;		// vector for Complex number
  data_C.clear(); data_C.reserve(nn);
  for(int ij=0;ij<nn;ij++) {
    fft::dft::Complex tempComp(outAmp[ij], 0.); // Setting the Real Part
    data_C.push_back(tempComp);
  }

  /** d-FFT */

  std::cout << " DFT Starts...." << std::endl;
  fft::dft fft_straight(data_C);
  fft_straight.doDFT();
  fft::dft::CNArray out_data_C = fft_straight.getDFT();
  std::cout << " DFT Ends...." << std::endl;

  std::vector<double> cBin,cAmp;
  cBin.clear(); cBin.reserve(nn/2);
  cAmp.clear(); cAmp.reserve(nn/2);
  for(int ij=0;ij<nn/2;ij++) {
    cBin.push_back(ij/tPD);
    double tmpAmp = abs(out_data_C[ij]);
    cAmp.push_back(tmpAmp);
  }

  /** Inverse d-FFT */

  fft::dft::CNArray data_I = fft_straight.getFullDFT();
  data_I[0] = {0, 0}; data_I[nn - 1] = {0, 0};

  std::cout << " iDFFT Starts...." << std::endl;
  fft::dft fft_inverse(data_I);
  fft_inverse.doiDFT();
  fft::dft::CNArray out_data_I = fft_inverse.getFullDFT();
  std::cout << " iDFFT Ends...." << std::endl;

  std::vector<double> iBin,iAmp;
  iBin.clear();iAmp.clear();
  for(int ij=0;ij<nn;ij++) {
    iBin.push_back(outPos[ij]);
    iAmp.push_back(real(out_data_I[ij]));
  }

  TCanvas *c1 = new TCanvas("c1","c1",2400,2400);
  c1->Divide(1,4);

  TGraph* h3 = new TGraph(inputDataPt, &pos0[0], &amp0[0]); // Gen
  TGraph* h0 = new TGraph(nn, &outPos[0], &outAmp[0]);	  // Pad
  TGraph* h1 = new TGraph(int(nn/2), &cBin[0], &cAmp[0]);	  // d-FFT
  TGraph* h2 = new TGraph(nn, &iBin[0], &iAmp[0]);	  // id-FFT
  
  c1->cd(1);
  h3->SetTitle("Generated");
  h3->Draw("AL*");
  // h3->GetXaxis()->SetRangeUser(0., tPD);
  c1->cd(2);
  h0->SetTitle("Padded");
  h0->Draw("AL");
  // h0->GetXaxis()->SetRangeUser(0., tPD);
  c1->cd(3);
  h1->SetTitle("DFT");
  h1->Draw("AL*");
  gPad->SetLogy(1);
  h1->GetXaxis()->SetRangeUser(0, 5.0);
  h1->SetMinimum(1);
  // h1->SetMaximum(1e10);
  c1->cd(4);
  h2->SetTitle("Inverse transform");
  h2->Draw("AL");
  // h2->GetXaxis()->SetRangeUser(0., tPD);

  c1->SaveAs("fft.pdf");
  // c1->SaveAs("fft.C");
  
  return 0;
}
