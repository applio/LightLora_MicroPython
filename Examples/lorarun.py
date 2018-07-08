import utime
from LightLora import lorautil
# a really ugly example using the LightLora micropython library
# do:
#      import lorarun
#      lorarun.doreader()
# to start running a loop test. Ctrl-C to stop.
# this ping-pongs fully with the Arduino LightLora example
def doreader():
	lr = lorautil.LoraUtil()	# the LoraUtil object
	endt = utime.time() + 2
	startTime = utime.time()
	ctr = 0
	while True:
		if lr.is_packet_available():
			packet = None
			try:
				packet = lr.read_packet()
				if packet and packet.msg_txt:
					txt = packet.msg_txt
					lr.send_packet(0xff, 0x41, (txt + str(ctr)).encode())
					endt = utime.time() + 4
					etime = str(int(utime.time() - startTime))
					print("@" + etime + "r=" + str(txt))
				ctr = ctr + 1
			except Exception as ex:
				print(str(ex))
		if utime.time() > endt:
			lr.send_packet(0xff, 0x41, ('P Lora' + str(ctr)).encode())
			ctr = ctr + 1
			endt = utime.time() + 4
		else:
			utime.sleep_ms(50)
