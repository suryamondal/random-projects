
const int     daysInAweek          = 7;
const TString dayTags[daysInAweek] =
  { "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday" };

const int     binsInAday           = 24. * 60;

// Day -> Hour, Temperature
std::map<TString, std::vector<std::tuple<TString,double>>> setTemperature{
  { "Monday",    {std::make_tuple("06:00", 22.),
		  std::make_tuple("08:30", 18.),
		  std::make_tuple("12:00", 21.),
		  std::make_tuple("13:30", 18.),
		  std::make_tuple("17:30", 22.),
		  std::make_tuple("23:00", 18.) } },
  { "Tuesday",   {std::make_tuple("06:00", 22.),
		  std::make_tuple("08:30", 18.),
		  std::make_tuple("12:00", 21.),
		  std::make_tuple("13:30", 18.),
		  std::make_tuple("17:30", 22.),
		  std::make_tuple("23:00", 18.) } },
  { "Wednesday", {std::make_tuple("06:00", 22.),
		  std::make_tuple("08:30", 18.),
		  std::make_tuple("12:00", 21.),
		  std::make_tuple("13:30", 18.),
		  std::make_tuple("17:30", 22.),
		  std::make_tuple("23:00", 18.) } },
  { "Thursday",  {std::make_tuple("06:00", 22.),
		  std::make_tuple("08:30", 18.),
		  std::make_tuple("12:00", 21.),
		  std::make_tuple("13:30", 18.),
		  std::make_tuple("17:30", 22.),
		  std::make_tuple("23:00", 18.) } },
  { "Friday",    {std::make_tuple("06:00", 22.),
		  std::make_tuple("08:30", 18.),
		  std::make_tuple("12:00", 21.),
		  std::make_tuple("13:30", 18.),
		  std::make_tuple("17:30", 22.),
		  std::make_tuple("24:00", 18.) } },
  { "Saturday",  {std::make_tuple("08:00", 22.),
		  std::make_tuple("09:30", 18.),
		  std::make_tuple("13:30", 21.),
		  std::make_tuple("14:30", 18.),
		  std::make_tuple("18:30", 22.),
		  std::make_tuple("24:00", 18.) } },
  { "Sunday",    {std::make_tuple("08:00", 22.),
		  std::make_tuple("09:30", 18.),
		  std::make_tuple("13:30", 21.),
		  std::make_tuple("14:30", 18.),
		  std::make_tuple("18:30", 22.),
		  std::make_tuple("23:00", 18.) } }
};


void plot() {

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
  temperature_plot->GetXaxis()->SetNdivisions(-24);
  gPad->SetGrid();

  // printing set temperature on histogram

  TLatex latex;
  latex.SetTextSize(0.025);
  latex.SetTextAlign(22);  // centered
  latex.SetTextAngle(45);
  for(auto item : setTemperature) {   // map items
    auto dayName = std::get<0>(item); // TString
    auto setTemp = std::get<1>(item); // vector
    int biny = temperature_plot->GetYaxis()->FindBin(dayName.Data());
    double binCentery = temperature_plot->GetYaxis()->GetBinCenter(biny);
    std::cout<<" day "<<dayName<<" biny "<<biny<<" binCentery "<<binCentery<<std::endl;
    for( auto element : setTemp) {    // tuple
      auto hour = std::get<0>(element);
      auto temp = std::get<1>(element);
      int HH, mm;
      sscanf(hour, "%d:%d", &HH, &mm);
      double hourAngle = HH + mm/60.;
      int binx = temperature_plot->GetXaxis()->FindBin(hourAngle);
      double binCenterx = temperature_plot->GetXaxis()->GetBinCenter(binx);
      std::cout<<"\t HH "<<HH<<" mm "<<mm<<" binx "<<binx<<" binCenterx "<<binCenterx<<" set "<<temp<<std::endl;
      latex.DrawLatex(binCenterx, binCentery, TString::Format("%.1f",temp).Data());
    }}
}
