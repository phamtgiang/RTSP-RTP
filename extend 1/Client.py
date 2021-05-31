import tkinter.messagebox as tkMessageBox
from tkinter import *
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os
import time
from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"


class Client:
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT

    SETUP = 0
    PLAY = 1
    PAUSE = 2
    TEARDOWN = 3

    
    #Statistics variables:
    statTotalBytes = 0         #Total number of bytes received in a session
    statStartTime = 0.0        #Time in milliseconds when start is pressed
    statTotalPlayTime = 0.0    #Time in milliseconds of video playing since beginning
    counter = 0

    # Initiation..
    def __init__(self, master, serveraddr, serverport, rtpport, filename):
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.handler)
        self.videoDataRate = 0   # Rate of video data received in bytes/s
        self.Packetlossrate = 0  # RTP packet loss rate ( % )
        self.createWidgets()
        self.serverAddr = serveraddr
        self.serverPort = int(serverport)
        self.rtpPort = int(rtpport)
        self.fileName = filename
        self.rtspSeq = 0
        self.sessionId = 0
        self.requestSent = -1
        self.teardownAcked = 0
        self.connectToServer()
        self.frameNbr = 0


    def createWidgets(self):
        """Build GUI."""
        # Create Setup button
        self.setup = Button(self.master, width=20, padx=3, pady=3)
        self.setup["text"] = "Setup"
        self.setup["command"] = self.setupMovie
        self.setup.grid(row=1, column=0, padx=2, pady=2)

        # Create Play button
        self.start = Button(self.master, width=20, padx=3, pady=3)
        self.start["text"] = "Play"
        self.start["command"] = self.playMovie
        self.start.grid(row=1, column=1, padx=2, pady=2)

        # Create Pause button
        self.pause = Button(self.master, width=20, padx=3, pady=3)
        self.pause["text"] = "Pause"
        self.pause["command"] = self.pauseMovie
        self.pause.grid(row=1, column=2, padx=2, pady=2)

        # Create Teardown button
        self.teardown = Button(self.master, width=20, padx=3, pady=3)
        self.teardown["text"] = "Teardown"
        self.teardown["command"] = self.exitClient
        self.teardown.grid(row=1, column=3, padx=2, pady=2)

        # Create a label to display the movie
        self.label = Label(self.master, height=19)
        self.label.grid(row=0, column=0, columnspan=4, sticky=W + E + N + S, padx=5, pady=5)

        # Create videoDateRate
        self.label2 = Label(self.master, height=2,text=("Video data rate : " + str(self.videoDataRate) + " (bytes/s) "))
        self.label2.grid(row=2, column=1, columnspan=1, padx=5, pady=5)

        # Create videoPacketLossRate
        self.label3 = Label(self.master, height=2, text=("RTP Packet Loss Rate : " + str(self.Packetlossrate) + " (%) "))
        self.label3.grid(row=3, column=1, columnspan=1, padx=5, pady=5)

    def setupMovie(self):
        """Setup button handler."""
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)
    def exitClient(self):
        """Teardown button handler."""
        self.sendRtspRequest(self.TEARDOWN)
        self.master.destroy()  # Close the gui window
        os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT)  # Delete the cache image from video
        print("\nPacket loss rate : " + str(self.Packetlossrate) + " ( % ) " +  '\n')
        print("\nVideo data rate : " + str(self.videoDataRate) + " ( bytes/second )" + '\n')

    def pauseMovie(self):
        """Pause button handler."""
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)

    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:
            # Create a new thread to listen for RTP packets
            threading.Thread(target=self.listenRtp).start()
            self.playEvent = threading.Event()
            self.playEvent.clear()
            self.sendRtspRequest(self.PLAY)

    def listenRtp(self):
        """Listen for RTP packets."""
        
        while True:
            try:
                data = self.rtpSocket.recv(20480)   # read most 20480 bytes

                if data:
                    rtpPacket = RtpPacket()
                    rtpPacket.decode(data) 
                    curTime = time.time()
                    self.statTotalPlayTime += curTime - self.statStartTime
                    self.statStartTime = curTime

                    print("Current Seq Num : " + str(rtpPacket.seqNum()))
                    payload_len = rtpPacket.__sizeof__()
                    #payload_len = int(data)
                    
                    try:
                        if self.frameNbr + 1 != rtpPacket.seqNum():
                            self.counter +=1
                            print("\npacket loss\n")
                        currFrameNbr = rtpPacket.seqNum()
                        self.Packetlossrate = float(self.counter / self.frameNbr)
                    except:
                        print("seqNum() error")
                        traceback.print_exc(file = sys.stdout)
                    if currFrameNbr > self.frameNbr:  # Discard the late packet
                        self.frameNbr = currFrameNbr
                        self.updateMovie(self.writeFrame(rtpPacket.getPayload()))
                    if self.statTotalPlayTime == 0 :
                        self.videoDataRate = 0
                    else:
                        self.videoDataRate = round(float(self.statTotalBytes/self.statTotalPlayTime),1)
                    self.updateVideoDateRate()
                    self.statTotalBytes += payload_len
                    self.updatePackLossRate()
            except:
                # Stop listening upon requesting PAUSE or TEARDOWN
                if self.playEvent.isSet():
                    break

                # Upon receiving ACK for TEARDOWN request,
                # close the RTP socket
                if self.teardownAcked == 1:
                    self.rtpSocket.shutdown(socket.SHUT_RDWR)
                    self.rtpSocket.close()
                    break

        
    def writeFrame(self, data):
        """Write the received frame to a temp image file. Return the image file."""
        cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
        file = open(cachename, "wb")
        file.write(data)
        file.close()

        return cachename

    def updateMovie(self, imageFile):
        """Update the image file as video frame in the GUI."""
        photo = ImageTk.PhotoImage(Image.open(imageFile))
        self.label.configure(image=photo, height=288)
        self.label.image = photo

    def connectToServer(self):
        """Connect to the Server. Start a new RTSP/TCP session."""
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
        except:
            tkMessageBox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' % self.serverAddr)

    def sendRtspRequest(self, requestCode):
        """Send RTSP request to the server."""
        # -------------
        # TO COMPLETE
        # -------------

        # Setup request
        if requestCode == self.SETUP and self.state == self.INIT:
            threading.Thread(target=self.recvRtspReply).start()
            # Update RTSP sequence number.
            self.rtspSeq = 1

            # Write the RTSP request to be sent.
            request = ( "SETUP " + str(self.fileName) + " RTSP/1.0 " + "\n"
                        "CSeq: " + str(self.rtspSeq) + "\n"
                        "Transport: RTP/UDP; client_port= " + str(self.rtpPort))

            # Keep track of the sent request.
            self.requestSent = self.SETUP

        # Play request
        elif requestCode == self.PLAY and self.state == self.READY:
            self.statStartTime = time.time()
            # Update RTSP sequence number.
            self.rtspSeq = self.rtspSeq + 1

            # Write the RTSP request to be sent.
            request = ("PLAY " + str(self.fileName) + " RTSP/1.0 " + "\n" +
                        "CSeq: " + str(self.rtspSeq) + "\n" +
                        "Session: " + str(self.sessionId))

            # Keep track of the sent request.
            self.requestSent = self.PLAY

        # Pause request
        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            # Update RTSP sequence number.
            self.rtspSeq = self.rtspSeq + 1

            # Write the RTSP request to be sent.
            request = ( "PAUSE " + str(self.fileName) + " RTSP/1.0 " + "\n" +
                        "CSeq: " + str(self.rtspSeq) + "\n" +
                        "Session: " + str(self.sessionId))

            # Keep track of the sent request.
            self.requestSent = self.PAUSE

        # Teardown request
        elif requestCode == self.TEARDOWN and not self.state == self.INIT:
            # Update RTSP sequence number.
            self.rtspSeq = self.rtspSeq + 1

            # Write the RTSP request to be sent.
            request = ( "TEARDOWN " + str(self.fileName) + " RTSP/1.0" + "\n"
                        "CSeq: " + str(self.rtspSeq) + "\n"
                        "Session: " + str(self.sessionId))

            # Keep track of the sent request.
            self.requestSent = self.TEARDOWN
        else:
            return


        # Send the RTSP request using rtspSocket.
        self.rtspSocket.send(request.encode("utf-8"))

        print('\nData sent:\n' + request)

    def recvRtspReply(self):
        """Receive RTSP reply from the server."""
        while True:
            reply = self.rtspSocket.recv(1024)

            if reply:
                self.parseRtspReply(reply.decode("utf-8"))

            # Close the RTSP socket upon requesting Teardown
            if self.requestSent == self.TEARDOWN:
                self.rtspSocket.shutdown(socket.SHUT_RDWR)
                self.rtspSocket.close()
                break

    def parseRtspReply(self, data):
        """Parse the RTSP reply from the server."""
        lines = data.split('\n')
        seqNum = int(lines[1].split(' ')[1])

        # Process only if the server reply's sequence number is the same as the request's
        if seqNum == self.rtspSeq:
            session = int(lines[2].split(' ')[1])
            # New RTSP session ID
            if self.sessionId == 0:
                self.sessionId = session

            # Process only if the session ID is the same
            if self.sessionId == session:
                if int(lines[0].split(' ')[1]) == 200:
                    if self.requestSent == self.SETUP:
                        # -------------
                        # TO COMPLETE
                        # -------------
                        # Update RTSP state.
                        self.state = self.READY

                        # Open RTP port.
                        self.openRtpPort()
                    elif self.requestSent == self.PLAY:
                        self.state = self.PLAYING
                    elif self.requestSent == self.PAUSE:
                        self.state = self.READY

                        # The play thread exits. A new thread is created on resume.
                        self.playEvent.set()
                    elif self.requestSent == self.TEARDOWN:
                        self.state = self.INIT

                        # Flag the teardownAcked to close the socket.
                        self.teardownAcked = 1



    def openRtpPort(self):
        """Open RTP socket binded to a specified port."""
        # -------------
        # TO COMPLETE
        # -------------
        # Create a new datagram socket to receive RTP packets from the server
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Set the timeout value of the socket to 0.5sec
        self.rtpSocket.settimeout(0.5)

        try:
            # Bind the socket to the address using the RTP port given by the client user
            self.state = self.READY
            self.rtpSocket.bind(('', self.rtpPort))
        except:
            tkMessageBox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' % self.rtpPort)

    def handler(self):
        """Handler on explicitly closing the GUI window."""
        self.pauseMovie()
        if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else:  # When the user presses cancel, resume playing.
            self.playMovie()

    def updateVideoDateRate(self):
        self.label2.configure(text="VideoDateRate : " + str(self.videoDataRate) + " (bytes/s)")
    def updatePackLossRate(self):
        self.label3.configure(text="PacketLossRate : " + str(self.PacketLossRate) + " (%) ")

