PWC Telemetry Processor V2 - User Guide
Welcome to the PWC Telemetry Processor! This application is designed to take GPS activity files from your rides and convert them into detailed telemetry data, including estimated Engine RPM and Fuel Consumption.
This guide will walk you through how to use the application effectively.
Table of Contents
1.	Quick Start: Generating Your First File
2.	Understanding the Main Window
3.	Managing Profiles (The "Training" System)
4.	How the Calculations Work (A Deeper Dive)
5.	Supported File Formats
6.	Troubleshooting & FAQ
________________________________________
1. Quick Start: Generating Your First File
Follow these steps to get your first telemetry file in minutes.
1.	Launch the Application: Run the PWC-Telmetry-Processor.py script. The main window will appear.
2.	Select Your GPS File: Click the "Browse..." button and locate the .gpx file from your jet ski ride.
3.	Choose a Jet Ski Profile: From the "Jet Ski Profile" dropdown, select the profile that best matches the PWC used for the ride (e.g., "Yamaha VX Cruiser HO").
4.	Set Ride Conditions: Adjust the values for Rider Weight, Fuel Load, etc., to match the conditions of that specific trip. These act as modifiers for the calculation.
5.	Generate Data: Click the green "Generate Telemetry Data" button.
6.	Save Your File: A "Save As" dialog will appear. Choose a location and name for your output file. You can save as a .csv (recommended for most telemetry software) or .xlsx (Excel) file.
7.	Done! The application will process the data and save the file. You'll see a success message in the log and a confirmation popup.
________________________________________
2. Understanding the Main Window
The main application window is divided into three sections:
•	Setup:
o	Input File: Where you select your source GPS file.
o	Jet Ski Profile: This is the most important setting. It tells the application which performance model (Speed vs. RPM, RPM vs. Fuel) to use as its baseline.
o	Manage Profiles: This button opens the "training" interface (see Section 3).
•	Ride Conditions:
o	These are modifiers that adjust the baseline profile. For example, a higher rider weight or "rough" water conditions will cause the application to estimate slightly higher RPM and fuel usage for the same speed.
•	Status Log:
o	This window provides real-time feedback on what the application is doing, from parsing files to saving the final output. Any errors will also be displayed here.
________________________________________
3. Managing Profiles (The "Training" System)
This is the most powerful feature of the application. It allows you to fine-tune the performance models to perfectly match a specific PWC.
To access it, click the "Manage Profiles..." button.
•	How it Works: The application's core data is stored in the profiles.json file. The Profile Manager is a user-friendly interface for editing this file.
•	Editing a Profile:
1.	Select the profile you want to edit from the dropdown menu at the top of the Profile Manager window.
2.	The current data points for the RPM Model and Fuel Model will load into the entry fields.
3.	To "train" the system, simply change these numbers. For example, if you know your ski actually idles at 1400 RPM instead of 1300, you can change that value.
4.	The data points must be in ascending order.
•	Saving Changes:
o	When you are finished editing, click the "Save All Profiles and Close" button. This will overwrite the profiles.json file with your new data. The main application will automatically reload the updated profiles.
•	Creating a New Profile (Advanced):
1.	Open the profiles.json file in a text editor.
2.	Copy an existing profile block (e.g., the entire "Yamaha VX Cruiser HO" block, from { to }).
3.	Paste it and change the name (e.g., "Kawasaki Ultra 310").
4.	Edit the RPM and Fuel data points to create a new baseline model for that ski.
5.	Save the file and restart the application. Your new profile will now appear in the dropdown.
________________________________________
4. How the Calculations Work (A Deeper Dive)
1.	File Parsing: The application first extracts a simple list of timestamps and speeds from your source GPS file.
2.	Profile Selection: It loads the speed_mph vs. rpm data points from your selected profile.
3.	RPM Estimation: It uses a mathematical process called linear interpolation to estimate the engine's RPM for every single speed data point in your file.
4.	Condition Adjustment: It applies the "Ride Conditions" as percentage-based multipliers to the estimated RPM.
5.	Fuel Rate Estimation: It then takes the final, adjusted RPM for each data point and uses the profile's rpm vs. lph (Liters Per Hour) model to interpolate the fuel consumption rate at that exact moment.
6.	Cumulative Calculation: Finally, it calculates the fuel used between each data point (usually one second) and adds it to a running total to get the "Fuel Used (L)" column.
________________________________________
5. Supported File Formats
•	Input: .gpx files
•	Output: .csv (Comma-Separated Values), .xlsx (Microsoft Excel).
o	Recommendation: Use .csv for maximum compatibility with telemetry overlay software like Telemetry Overlay, DashWare, or RaceRender.
________________________________________
6. Troubleshooting & FAQ
•	Error: "Could not load 'profiles.json'..."
o	Make sure the profiles.json file is in the same directory as the application script and that its format is valid. You can use an online JSON validator to check for errors like missing commas or brackets.
•	Error: "Unsupported file type"
o	The application only supports .gpx files. Ensure your file has one of these extensions.
o	This means the GPS was not turned on in your GoPro's settings during recording. The application cannot process video files without this embedded GPS data.
•	The RPM or Fuel numbers seem too high/low.
o	This is exactly what the Profile Manager is for! Open it and "train" the models to better match your real-world observations. Start by adjusting the RPM model first, as the fuel model depends on it.
•	Can I add more data points to a model?
o	Yes. To do this, you must edit the profiles.json file manually. Make sure you add a new speed and a new RPM value (or a new RPM and LPH value) to the respective lists, keeping the number of items in both lists identical.

