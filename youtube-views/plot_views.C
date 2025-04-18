
void plot_views(const char* fileTagName) {
  std::string fileTag = fileTagName;

  std::string fileName = "data/" + fileTag + "_views.csv";
  std::ifstream file(fileName.c_str());
  if (!file.is_open()) {
    std::cerr << "Cannot open file! " << fileName << std::endl;
    return;
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

  int n = times.size();
  TGraph* graph = new TGraph(n, times.data(), views.data());
  graph->SetTitle((fileTag + ";Time;Views").c_str());
  graph->SetMarkerStyle(20);
  graph->SetMarkerSize(0.3);
  graph->SetLineColor(kBlue);

  TCanvas* c1 = new TCanvas("c1", "Views Over Time", 800, 600);
  c1->SetGrid();

  // Axis formatting for time
  graph->GetXaxis()->SetTimeDisplay(1);
  graph->GetXaxis()->SetTimeFormat("%H:%M");
  graph->GetXaxis()->SetTitle("Time (HH:MM)");

  graph->Draw("APL");

  c1->SaveAs(("plots/" + fileTag + ".pdf").c_str());

}
