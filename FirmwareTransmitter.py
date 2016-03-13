#Copyright (C) 2016 Westin Sykes
#This program is free software; you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation; either version 3 of the License, or
#(at your option) any later version.
#This program is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#You should have received a copy of the GNU General Public License
#along with this program; if not, write to the Free Software Foundation,
#Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA


import argparse
import fnmatch
import hashlib
import os
import re
import socket
import sys
import time

#TODO: Consider adding a way to extract files.

#Defines socket timeout time in seconds.
SOCKET_TIMEOUT = 5

#This is used in SendCommand to determine when a response is complete.
TERMINAL_READY_INDICATOR = re.compile("(^|\n|\r)> $")

DEVICE_CONNECTION_RESPONSE = "Firmware Upgrader\n\r"

#Defines the names of files on the device that must not be deleted.
VITAL_DEVICE_FILE_LIST = ["init.lua", "init.lc", "FirmwareUpgrader.lua", "FirmwareUpgrader.lc"]



def InitializeDeviceConnection(address, port):
	"""
	Connects to the device and waits for the expected response from it on connection.
	Returns a socket object on success and None otherwise.
	"""
	#Create socket and connect to the device.
	sock = socket.socket()
	sock.settimeout(SOCKET_TIMEOUT)
	try:
		sock.connect((address, port))
	except:
		print "Error connecting to device:", sys.exc_value
		return None

	#Device should send a hello message
	msg = ReceiveMessage(sock)
	if msg != "Firmware Upgrader\n\r":
		print "Unable to get connection message from device!"
		if msg != None and msg != "":
			print('Received: "%s"' % msg)
		sock.close()
		return None

	#Wait until we get the terminal ready indicator after sending a blank message.
	sock.send("\n\r")
	startTime = time.time()
	terminalReady = False
	while not terminalReady:
		msg = ReceiveMessage(sock)
		if msg:
			if TERMINAL_READY_INDICATOR.search(msg):
				terminalReady = True
		if startTime + SOCKET_TIMEOUT < time.time():
			#We timed out waiting!
			print "Failed to receive the terminal ready indicator!"
			sock.close()
			return None
	return sock


def ReceiveMessage(sock):
	"""
	Receives message from socket and checks for errors.
	Returns the response on success and None otherwise.
	Will print out exceptions that are not timeouts.
	"""
	try:
		return sock.recv(4096)
	except:
		print "Error receiving device connection message:", sys.exc_value
		return None


def SendCommand(sock, command):
	"""
	Sends a command to the device and waits for the response.
	Returns the response not including the "terminal ready indicator"
	Returns None on error.
	"""
	#Send the command
	if sock.send(command) != len(command):
		print "Failed to send command: \"%s\"" % command
		return None
	#Wait until we get the prompt back ("> ") and store the rest of the text to be returned
	responseData = ""
	while True:
		msg = ReceiveMessage(sock)
		if msg == None:
			print "Failed to get message chunk. Received: \"%s\"" % responseData
			return None
		responseData += msg
		#See if we received the "terminal ready indicator". If we did, strip it off and return
		terminalReadySearch = TERMINAL_READY_INDICATOR.search(responseData)
		if terminalReadySearch:
			#We found the end. Just need to strip it off. Note that this operation could lose data if more comes
			# after the "terminal ready indicator"
			return responseData[:terminalReadySearch.span()[0]]


def SendCommandAndCheckResponse(sock, command, expectedResponse, verbose=False):
	"""
	Sends a command using SendCommand() and checks to see that the response is as expected.
	Returns None on success and the unexpected response on failure.
	"""
	sendResponse = SendCommand(sock, command)
	if sendResponse == None:
		#Something went wrong, but we don't have any text returned.
		#Print out an error and return an empty string.
		print 'Error executing command: "%s"' % command
		return ""
	#See if the returned text is as expected.
	if sendResponse != expectedResponse:
		if sendResponse != None:
			if verbose:
				print "Unexpected response: \"%s\"" % sendResponse
		return sendResponse
	else:
		#We got what we expected. Return None to indicate success.
		return None


def RemoveFileOnDevice(sock, filename, verbose=False, force=False):
	"""
	Removes a file and checks to make sure it is gone.
	If force is False, removing files in VITAL_DEVICE_FILE_LIST will fail.
	Returns True on success and False otherwise.
	"""
	if verbose:
		print 'Removing file: \"%s\"' % filename
	if force == False and filename in VITAL_DEVICE_FILE_LIST:
		print "Error! Removing vital files not allowed!"
		return False
	returnText = SendCommandAndCheckResponse(sock, 'file.remove("%s")' % filename, "")
	if returnText == None:
		#It seems that we could remove the file.
		return True
	else:
		print "Error! Remove command failed to return expected response! Returned: \"%s\"" % returnText
		return False


def RebootDevice(sock, verbose=False):
	"""
	Reboots the connected device.
	Returns True on success and False otherwise.
	"""
	if verbose:
		print "Rebooting Device"
	returnText = SendCommandAndCheckResponse(sock, "tmr.alarm(0, 1000, tmr.ALARM_SINGLE, node.restart)",  "")
	if returnText == None:
		#It seems that we could remove the file.
		return True
	else:
		if verbose:
			print "Error! Restart command failed to return expected response! Returned: \"%s\"" % returnText
		return False


def SendFile(sock, files, i, writeSize):
	"""
	Transmits a file to the device.
	Takes a valid socket connected to device, the list of files, the file index, and the number of bytes to send at a time.
	of the file to be transmitted.
	Socket receive buffer must be clear with the device ready for message. This means
	the "> " has already been received indicating the device is ready for a command.
	Returns True on success and False otherwise.
	"""
	filePath = files[i]
	print "Transmitting: %s (%i/%i)..." % (filePath, i+1, len(files))
	fileName = os.path.split(filePath)[1]
	if not fileName:
		#Something went wrong
		print "Internal error while processing file!"
		return False

	#Read the file and convert it to a string of binaries that the lua interpreter will like.
	data = None
	with open(filePath, 'rb') as f:
		data = ["\%i" % ord(x) for x in f.read()]
	#Remove the file if it already exists.

	if not RemoveFileOnDevice(sock, fileName, False, True):
		return False

	#Open the file.
	if SendCommandAndCheckResponse(sock, 'file.open("%s", "w")' % fileName, "", True) != None:
		print "Unable to open file!"
		return False

	#Split up file into chunks and send each one.
	bytesSent = 0
	success = True
	while True:
		#Get the string to send that is the next up to writeSize bytes long.
		dataToWrite = ''.join([data[i] for i in xrange(bytesSent, min(bytesSent+writeSize, len(data)))])
		if not dataToWrite:
			break
		bytesSent += writeSize
		if SendCommandAndCheckResponse(sock, 'file.write("%s")' % dataToWrite, "", True) != None:
			print "Unable to write to file!"
			success = False
			break

	if SendCommandAndCheckResponse(sock, 'file.close()', "", True) != None:
		print "Unable to close file! Device may need to be reset."
		return False

	return success


def FindAllFilesToTransmit(targetList, excludeFilterList, recursiveSearch):
	"""
	Searches through files and folders to make a list of file paths that need to be transmitted.
	This prints an appropriate failure message on failure.
	targetList is a list of paths to files and folders
	excludeFilterList is a list of glob patterns to exclude files found using the file's path.
	recursiveSearch indicates whether subdirectories are searched.
	Returns a list of file paths on success and None on failure.
	"""
	files = []
	#Process all target files and folders
	for target in targetList:
		#If we were passed a file, we just need to process that one. If we got a directory, find all the files recursively.
		if os.path.isfile(target):
			files.append(target)
		elif os.path.isdir(target):
			for (dirpath, dirnames, filenames) in os.walk(target):
				#If we aren't searching recursively, remove all directories in dirnames
				if not recursiveSearch:
					del dirnames[:]
				#Iterate through all filenames
				for filename in filenames:
					filePath = os.path.join(dirpath, filename)
					#Check for duplicates
					for processedFile in files:
						if filename == os.path.split(processedFile)[1]:
							print "Duplicate file found! This is not supported."
							print filePath
							print processedFile
							return None
					#Now that we know we have no duplicate, add it to the list of files if we don't want to exclude it.
					excludeFile = False
					if excludeFilterList:
						for excludeFilter in excludeFilterList:
							if fnmatch.fnmatch(filePath, excludeFilter):
								#We have a match on an exclude filter. We need to exclude the file.
								excludeFile = True
								break
					if not excludeFile:
						#Add the file to the list since its not being excluded.
						files.append(filePath)
		else:
			print "Error! Unknown path!", target
			return None
	return files


def CompileAndRemoveLuaSource(sock, files, i):
	"""
	Compiles a lua file and removes the .lua file leaving the .lc file.
	Takes a valid socket connected to device, the list of files, and the index
	of the file to be compiled.
	Socket receive buffer must be clear with the device ready for message. This means
	the "> " has already been received indicating the device is ready for a command.
	Returns True on success and failure otherwise.
	"""
	success = False
	fileName = os.path.split(files[i])[1]
	print "Compiling: %s (%i/%i)..." % (fileName, i+1, len(files))
	extensionlessFileName, fileExtension = os.path.splitext(fileName)
	if fileExtension != ".lua":
		print "Internal error! Invalid file type for compilation: \"%s\"" % fileExtension
		return False
	compiledFileName = extensionlessFileName + ".lc"
	#First try to compile it.
	compileRet = SendCommandAndCheckResponse(sock, 'node.compile("%s")' % fileName, "", True)
	if compileRet == None:
		#Now lets delete the old file.
		if RemoveFileOnDevice(sock, fileName, True, True):
			success = True
	elif compileRet:
		#If there was a compilation error, print it out.
		print "Compilation error!\n%s" % compileRet
	if success:
		return True
	else:
		print "Failed to compile %s!" % fileName
		return False


def CleanApplicationFiles(sock, filesToSave, verbose):
	"""
	Removes all files from the device that are not in VITAL_DEVICE_FILE_LIST.
	Returns True on success and false otherwise.
	"""
	filenames = GetFilesOnDevice(sock)
	#Make sure nothing went wrong.
	if filenames == None:
		print "Unable to clean application files!"
		return False
	#If verbose is set, let the user know what we are doing and remove the files that should be removed.
	if verbose:
		print "Cleaning application files..."
	for fileName in filenames:
		if (filesToSave == None) or (fileName not in filesToSave):
			if not RemoveFileOnDevice(sock, fileName, verbose, False):
				#Something went wrong
				if verbose:
					print "Failed to clean application files!"
				return False
	#If we got here, everything went well.
	return True


def GetFilesOnDevice(sock):
	"""
	Gets and returns a list of all files on the device.
	This does not display vital system files.
	Returns None on failure.
	"""
	#This command should get us all the filenames in a string delimited with newlines.
	filenames = SendCommand(sock, "for k, _ in pairs(file.list()) do print(k) end")
	#Split the string to get a list.
	if filenames != None:
		#Parse filenames
		filenames = [x for x in re.split("[\n\r]", filenames) if x != "" and x not in VITAL_DEVICE_FILE_LIST]
	return filenames


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("targets", type=str, help="Path to file or folder to transmit", nargs="*")
	parser.add_argument("-a", "--address", type=str, help="IP address of device to be programmed", default="192.168.4.1")
	parser.add_argument("-c", "--compile", help="Compile .lua files into .lc files", action="store_true")
	parser.add_argument("-C", "--clean", help="Set this to remove all unused files currently on device.", action="store_true")
	parser.add_argument("-d", "--display", help="Displays all files to be sent without transmitting them. This can be useful for testing excludes.", action="store_true")
	parser.add_argument("-D", "--delete", type=str, help="Specifies a file to be deleted.", action="append")
	parser.add_argument("-e", "--exclude", type=str, help="Regular expression used to exclude input files.", action="append")
	parser.add_argument("-f", "--files", help="Displays the files currently on the device. This happens before making any changes.", action="store_true")
	parser.add_argument("-p", "--port", type=int, help="Port to use when connecting", default=23)
	parser.add_argument("-r", "--recursive", help="Indicates that the file search should recursively search through each directory", action="store_true")
	parser.add_argument("-R", "--reboot", help="Set this to reboot the device at the end", action="store_true")
	parser.add_argument("-s", "--save", type=str, help="Adds files to save for the case that the --clean option is used. This should not include internally managed files.", action="append")
	parser.add_argument("-S", "--size", type=int, help="Set the write size in bytes", default=50)
	args = parser.parse_args()


	files = FindAllFilesToTransmit(args.targets, args.exclude, args.recursive)
	if files == None:
		print "Unable to continue!"
		exit(1)

	#If use wants to just display files that would have been sent, do that.
	if args.display:
		print "\n".join(files)
		exit(0)

	sock = InitializeDeviceConnection(args.address, args.port)
	if sock == None:
		exit(1)

	if args.files:
		filesOnDevice = GetFilesOnDevice(sock)
		if filesOnDevice == None:
			print "Failed to get files on device"
			print "quitting."
			sock.close()
			exit(1)
		print "%i File%s on device:" % (len(filesOnDevice), "s"*(len(filesOnDevice)>1))
		print "\t" + "\n\t".join(filesOnDevice) + "\n"

	if args.clean:
		if not CleanApplicationFiles(sock, args.save, True):
			print "quitting."
			sock.close()
			exit(1)

	#Delete any files that need to be deleted.
	if args.delete:
		for fileTodelete in args.delete:
			if not RemoveFileOnDevice(sock, fileTodelete, True, False):
				print "quitting."
				sock.close()
				exit(1)

	#Open files and start sending
	success = True
	for i, filePath in enumerate(files):
		#Send the file
		if not SendFile(sock, files, i, args.size):
			print 'Failed to send file!'
			success = False

		#If the file is a .lua file and we need to compile it, compile the file then remove the .lua.
		if args.compile and success:
			if filePath.endswith(".lua"):
				if not CompileAndRemoveLuaSource(sock, files, i):
					success = False

		if not success:
			print "Failure! Removing potentially broken file."
			RemoveFileOnDevice(sock, files[i], True, False)
			break

	#If we need to reboot, do that before finishing.
	if args.reboot:
		RebootDevice(sock, True)

	if success:
		print "Finished!"
	else:
		print "Ending with errors!"

	sock.close()
	exit(not success)


if __name__ == "__main__":
	main()


