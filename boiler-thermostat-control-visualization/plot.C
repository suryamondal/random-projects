
const int     daysInAweek          = 7;
const TString dayTags[daysInAweek] =
  { "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday" };

const double  hoursInAday          = 24;
const int     binsInAday           = hoursInAday * 60;

// Day -> Hour, Temperature
std::map<TString, std::vector<std::tuple<TString,double>>> setTemperature{
  { "Sunday",    {std::make_tuple("06:00", 22.),
		  std::make_tuple("08:30", 18.),
		  std::make_tuple("12:00", 21.),
		  std::make_tuple("13:30", 18.),
		  std::make_tuple("17:30", 22.),
		  std::make_tuple("23:00", 18.) } },
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
		  std::make_tuple("00:00", 18.) } },
  { "Saturday",  {std::make_tuple("08:00", 22.),
		  std::make_tuple("09:30", 18.),
		  std::make_tuple("13:30", 21.),
		  std::make_tuple("14:30", 18.),
		  std::make_tuple("18:30", 22.),
		  std::make_tuple("00:00", 18.) } },
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

}
