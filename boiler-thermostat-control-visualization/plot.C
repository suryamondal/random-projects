
void plot() {

  const int daysInAweek = 7;
  const TString dayTags[daysInAweek] =
    { "Monday",
      "Tuesday",
      "Wednesday",
      "Thursday",
      "Friday",
      "Saturday",
      "Sunday" };

  const double hoursInAday = 24;
  const int    binsInAday  = hoursInAday * 60;

  TH2D *temperature_plot = new TH2D("temperature_plot",
				    "Temperature Plot in a Week",
				    binsInAday, 0., 24.,
				    daysInAweek, -0.5, daysInAweek - 0.5);
  temperature_plot->GetXaxis()->SetTitle("Hours in a day");
  temperature_plot->SetStats(0);
  for(int ij=daysInAweek; ij>0; ij--) {
    temperature_plot->GetYaxis()->SetBinLabel(ij, dayTags[daysInAweek - ij].Data());
  }

  temperature_plot->Draw("colz");

}
