import socket

SERVERDATA_INVALID:int = -1
SERVERDATA_RESPONSE_VALUE:int = 0
SERVERDATA_EXECCOMMAND:int = 2
SERVERDATA_AUTH_RESPONSE:int = 2
SERVERDATA_AUTH:int = 3

PACKETID_INVALID:int = -1
PACKETID_AUTH:int = 0
PACKETID_COMMAND:int = 1

class packet:
	def __init__(self, id:int, type:int, body:str) -> None:
		self.id = id
		self.type = type
		self.body = body
	
	def get_body(self) -> str:
		return self.body
	
	def to_bytes(self) -> bytes:
		size:int = len(self.body) + 10

		return bytes(
			size.to_bytes(4, "little", signed=True) +
			self.id.to_bytes(4, "little", signed=True) +
			self.type.to_bytes(4, "little", signed=True) +
			self.body.encode() +
			b'\0\0'
		)
	
	@classmethod
	def from_bytes(cls, data:bytes, size:int):
		id:int = int.from_bytes(data[0:4], "little", signed=True)
		type:int = int.from_bytes(data[4:8], "little", signed=True)
		body:str = data[8:-2].decode("utf-8") # Decode and discard null-terminators
		
		return cls(id, type, body)
		


class rcon:
	def __init__(self, address:str, port:int, password:str, timeout:float = 5.0, silent:bool = False) -> None:
		self.address = address
		self.port = port
		self.password = password
		self.is_authorized = False
		self.is_open = False
		self.silent = silent

		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.sock.settimeout(timeout)

		try:
			self.sock.connect((address, port))
			self.is_open = True
		except: # I'd really prefer only catch exceptions we care about, but it looks like we can get platform-specific exceptions
			self.is_open = False
			self.sock.close()

		if self.is_open:
			self.auth()
	
	def debug_output(self, output:str):
		if not self.silent:
			print(output)
	
	def is_ready(self) -> bool:
		return self.is_open and self.is_authorized
	
	def send(self, id:int, type:int, body:str):
		data:bytes = packet(id, type, body).to_bytes()

		try:
			self.sock.send(data)
		except:
			self.is_open = False
			self.sock.close()
	
	def recv(self):
		try:
			data:bytes = self.sock.recv(4)
		except:
			self.is_open = False
			self.sock.close()
			return packet(PACKETID_INVALID, SERVERDATA_INVALID, '')

		size:int = int.from_bytes(data, "little", signed=True)

		try:
			data = self.sock.recv(size)
			return packet.from_bytes(data, size)
		except: # I'd really prefer only catch exceptions we care about, but it looks like we can get platform-specific exceptions
			self.is_open = False
			self.sock.close()

		return packet(PACKETID_INVALID, SERVERDATA_INVALID, '')
	
	def exec_command(self, command:str) -> str:
		if not self.is_ready():
			return ''
		
		self.send(PACKETID_COMMAND, SERVERDATA_EXECCOMMAND, command)
		response:packet = self.recv()

		if response.id != PACKETID_COMMAND or response.type != SERVERDATA_RESPONSE_VALUE:
			return ''
		
		return response.get_body()

	def auth(self):
		self.send(PACKETID_AUTH, SERVERDATA_AUTH, self.password)
		response:packet = self.recv()

		if response.id == PACKETID_INVALID:
			self.is_open = False
			self.sock.close()
			self.debug_output("Invalid RCON response")
			return
		elif response.type == SERVERDATA_RESPONSE_VALUE: # Should receive empty response first
			response = self.recv()
		else:
			self.debug_output("Unexpected RCON response")
			return
		
		if response.id != PACKETID_AUTH or response.type != SERVERDATA_AUTH_RESPONSE:
			self.debug_output(f"Failed to get authorization from {self.address}:{self.port}")
			return
		
		self.is_authorized = True # Success!
		self.debug_output("RCON authorized")

