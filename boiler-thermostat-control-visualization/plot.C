
const int     daysInAweek          = 7;
const TString dayTags[daysInAweek] =
  { "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday" };

const int     binsInAday           = 24 * 60;

// Day -> Hour, Temperature
std::map<TString, std::vector<std::tuple<TString,double>>> setTemperature {
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
		  std::make_tuple("17:30", 22.) } },
  { "Saturday",  {std::make_tuple("00:00", 18.),
		  std::make_tuple("08:00", 22.),
		  std::make_tuple("09:30", 18.),
		  std::make_tuple("13:30", 21.),
		  std::make_tuple("14:30", 18.),
		  std::make_tuple("18:30", 22.) } },
  { "Sunday",    {std::make_tuple("00:00", 18.),
		  std::make_tuple("08:00", 22.),
		  std::make_tuple("09:30", 18.),
		  std::make_tuple("13:30", 21.),
		  std::make_tuple("14:30", 18.),
		  std::make_tuple("18:30", 22.),
		  std::make_tuple("23:00", 18.) } }
};


// simulation parameter

const double waterMass         = 100;	// kg
const double systemCapacity    = 20;	// kW
const double heatLoss          = 0.1;	// kW/C
const double heatLoad          = 500;	// kg of air
const double airSpecificHeat   = 1.005;	// kJ/kg-C
const double waterSpecificHeat = 4.186; // kJ/kg-C
const double heatTransferCf    = 0.1;	// kW/C
const int    simulationCycle   = 10;	// 

const double outdoorTemperature[24] =	// C
  {
    9, // 0
    9, // 1
    8, // 2
    8, // 3
    8, // 4
    8, // 5
    9, // 6
    9, // 7
   10, // 8
   12, // 9
   15, // 10
   17, // 11
   17, // 12
   18, // 13
   19, // 14
   20, // 15
   19, // 16
   17, // 17
   15, // 18
   14, // 19
   13, // 20
   12, // 21
   11, // 22
   10  // 23
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

  TH2D *water_temperature = (TH2D*)temperature_plot->Clone("water_temperature");
  water_temperature->SetTitle("Water Temperature Plot in a Week");


  // making the set temperature readable

  std::map<TString, std::map<TString,double>> tProgram;
  for(auto item : setTemperature) {   // map items
    auto dayName = std::get<0>(item); // TString
    auto setTemp = std::get<1>(item); // vector
    for( auto element : setTemp) {    // tuple
      auto hour = std::get<0>(element);
      auto temp = std::get<1>(element);
      (tProgram[dayName])[hour] = temp;
    }}



  // simulation


  double lst_iT = 0, lst_wT, sT = 0;
  for(int sim = 0; sim<simulationCycle; sim++) {
    for(int ijy=daysInAweek; ijy>0; ijy--) {
      for(int ijx=1; ijx<=binsInAday; ijx++) {
	double hourAngle = temperature_plot->GetXaxis()->GetBinCenter(ijx);

	// Initialise

	if(!lst_iT) {
	  lst_iT = lst_wT = outdoorTemperature[int(hourAngle)];
	  temperature_plot-> SetBinContent(ijx, ijy, lst_iT);
	  water_temperature->SetBinContent(ijx, ijy, lst_wT);
	  continue; }

	auto search1 = tProgram.find(dayTags[daysInAweek - ijy]);
	if(search1 != tProgram.end()) {
	  int HH = int(hourAngle);
	  int mm = int((hourAngle - int(hourAngle)) * 60.);
	  TString time_str = TString::Format("%02i:%02i",HH,mm);
	  auto search2 = search1->second.find(time_str);
	  if(search2 != search1->second.end()) {
	    sT = search2->second;
	    std::cout<<" day_str "<<dayTags[daysInAweek - ijy]<<" time_str "<<time_str<<" sT "<<sT<<std::endl;
	  }
	}

	if(!sT) {continue;}

	// Projecting in this next bin

	double oT = outdoorTemperature[int(hourAngle)];
	bool isBoilerOn = (lst_iT < sT);

	double step = temperature_plot->GetXaxis()->GetBinWidth(ijx);
	step *= 3600.;		// in seconds

	double boilerHeat = isBoilerOn ? systemCapacity * step : 0;
	lst_wT += boilerHeat / (waterSpecificHeat * waterMass);
	double waterHeatLoss = (lst_wT - lst_iT) * heatTransferCf * step;
	lst_wT -= waterHeatLoss  / (waterSpecificHeat * waterMass);
	lst_iT += waterHeatLoss / (airSpecificHeat * heatLoad);
	double airHeatLoss = (lst_iT - oT) * heatLoss * step;
	lst_iT -= airHeatLoss / (airSpecificHeat * heatLoad);

	std::cout<<"\t\t sim "<<std::setw(3)<<sim<<" ijx "<<std::setw(5)<<ijx<<" ijy "<<std::setw(5)<<ijy<<std::endl;
	std::cout<<"\t\t oT "<<std::setw(6)<<oT<<" isBoilerOn "<<std::setw(6)<<isBoilerOn<<" lst_iT "<<std::setw(6)<<lst_iT<<" lst_wT "<<std::setw(6)<<lst_wT<<std::endl;

	temperature_plot-> SetBinContent(ijx, ijy, lst_iT);
	water_temperature->SetBinContent(ijx, ijy, lst_wT);
      }
    }
  } // for(int sim = 0; sim<simulationCycle; sim++) {


  TCanvas *c1 = new TCanvas("c1","c1",1000,600);
  c1->cd();
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

  TCanvas *c2 = new TCanvas("c2","c2",1000,600);
  c2->cd();
  water_temperature->Draw("colz");
  water_temperature->GetXaxis()->SetNdivisions(-24);
  gPad->SetGrid();

}
