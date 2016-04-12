--Copyright (C) 2016 Westin Sykes
--This program is free software; you can redistribute it and/or modify
--it under the terms of the GNU General Public License as published by
--the Free Software Foundation; either version 3 of the License, or
--(at your option) any later version.
--This program is distributed in the hope that it will be useful,
--but WITHOUT ANY WARRANTY; without even the implied warranty of
--MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
--GNU General Public License for more details.
--You should have received a copy of the GNU General Public License
--along with this program; if not, write to the Free Software Foundation,
--Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA


gpio.mode(0, gpio.INPUT, gpio.PULLUP)

local runMainApp = (gpio.read(0) == 1)
if file.list()["bootUpgrader"] then
	file.remove("bootUpgrader")
	runMainApp = false
end

local runFirmwareUpgrader = (runMainApp == false)

--Should be passed the name of the script that is either a .lc or .lua without the extension.
local function loadLuaOrLCFile(filename)
	if file.list()[filename .. ".lc"] then
		return loadfile(filename .. ".lc")
	else
		return loadfile(filename .. ".lua")
	end
end

if runMainApp then
	--Button is not pressed. Try to load the main application.
	print("Loading main application.")

	mainFunc, mainErrorText = loadLuaOrLCFile("main")

	if mainFunc then
		if not tmr.alarm(0, 2000, tmr.ALARM_SINGLE, mainFunc) then
			print("Unable to start timer for main application!")
		end
	else
		--Something went wrong in loading the application
		--We will run the firmware upgrader application.
		print("Unable to load main")
		print(mainErrorText)
		runFirmwareUpgrader = true
	end
end

if runFirmwareUpgrader then
	print("Running Firmware Upgrader.")

	upgraderFunc, recoverErrorText = loadLuaOrLCFile("FirmwareUpgrader")
	if upgraderFunc then
		if not tmr.alarm(0, 2000, tmr.ALARM_SINGLE, upgraderFunc) then
			print("Unable to start timer for firmware upgrader application!")
		end
	else
		--Something went wrong in loading the firmware upgrader application.
		print("Unable to load firmware upgrader application!")
		print(recoverErrorText)
	end
end

--Clean things up before booting whichever application we run.
loadLuaOrLCFile = nil
runFirmwareUpgrader = nil
runMainApp = nil
collectgarbage()
