sudo cp monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable monitor.service
sudo systemctl start monitor.service
