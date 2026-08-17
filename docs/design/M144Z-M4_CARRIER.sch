EESchema Schematic File Version 4
LIBS:M144Z-M4_CARRIER-cache
EELAYER 29 0
EELAYER END
$Descr A4 11693 8268
Sheet 1 1
Title "M144Z-M4 Mini Board JP_L/JP_R Pinout"
Date "2026-08-15"
Rev "G1-CANDIDATE"
Comp "Candidate import reference - physical header positions TBD"
Comment1 "JP_L/JP_R: odd pins outer column, even pins inner column"
Comment2 "GPIO function evidence is from user tests; header continuity remains to be verified"
$EndDescr
$Comp
L M144Z_M4_JP_L J1
U 1 1 1
P 3300 4000
F 0 "J1" H 3300 4725 60  0000 C CNN
F 1 "M144Z_M4_JP_L" H 3300 4625 50  0000 C CNN
	1    3300 4000
	1    0    0    -1
$EndComp
$Comp
L M144Z_M4_JP_R J2
U 1 1 2
P 7500 4000
F 0 "J2" H 7500 4725 60  0000 C CNN
F 1 "M144Z_M4_JP_R" H 7500 4625 50  0000 C CNN
	1    7500 4000
	1    0    0    -1
$EndComp
Text Notes 3300 5200 0    80   ~ 16
JP_L: 1=PB15 outer, 2=PF12 inner; row numbering from TF-card end
Text Notes 7500 5200 0    80   ~ 16
JP_R: 1=PC6 outer, 2=PC7 inner; row numbering from TF-card end
Text Notes 5500 5800 0    70   ~ 12
G1 candidate pinout reference. Do not freeze PCB until header continuity and mechanical dimensions are verified.
$EndSCHEMATC
