Class iTerm.Engine Extends %CSP.WebSocket
{

Parameter UseSession = 1;

Property sid As %String;

Property connected As %Boolean;

Property fd As %Integer;

Property pingInterval As %Integer [ InitialExpression = 25000 ];

Property pingTimeout As %Integer [ InitialExpression = 20000 ];

Property lastSend As %Integer;

Method Server() As %Status
{
  try {
    set username = $username
    set ..sid = %session.SessionId

    do ..connect()

    set init = 0

    set result = ..start()
    set ..fd = result."__getitem__"(0)
    set proc = result."__getitem__"(1)
    set timeout = 0
    for {
      set len = 32656
      set data = ..Read(.len, .sc, timeout)
      if $$$GETERRORCODE(sc) = $$$CSPWebSocketClosed {
        quit
      }
      if $$$GETERRORCODE(sc) '= $$$CSPWebSocketTimeout {
        do ..onReceive(data)
      }

      if ..connected {
        if proc.poll() = 0 {
          #; process finished
          quit
        }
        set output = ..readfd()
        if output'="" {
          do ..emit("pty-output", {"output": (output)})
          if 'init {
            set init = 1
            do ..init(username)
          }
        }
      }
      if (($zhorolog * 1000) - ..pingInterval) > ..lastSend {
        do ..Write(2)
        set data = ..Read(1, .sc, ..pingTimeout)
        if data'=3 {
          quit
        }
      }
      hang 0.01
    }
  } catch ex {
    do ..Write("oops: " _ ex.DisplayString())
  }
  quit ..EndServer()
}

Method init(username) [ Language = python ]
{
  import iris
  if "USE" in iris.system.Security.CheckUserPermission(username, "%Service_Login"):
    self.writefd(f'write $system.Security.Login("{username}")\n')
  self.writefd(f':clear\n')

  #; hide init input/output
  while self.readfd(1):
    pass
}

Method onReceive(data) [ Language = python ]
{
  import json
  if data[0:2] == "40":
    self.send(40, {"sid": self.sid})
    self.connected = 1

  if not self.connected:
    return

  if data[0:2] == "42":
    [event, payload] = json.loads(data[2:])
    if event == "pty-input":
      self.writefd(payload["input"])
}

Method emit(event, data) [ Language = python ]
{
  if not isinstance(data, dict):
    import json
    data = json.loads(data._ToJSON())
  self.send(42, [event, data])
}

Method Write(data As %String) As %Status
{
  set ..lastSend = $zhorolog * 1000
  quit ##super(data)
}

Method send(type, payload) [ Language = python ]
{
  import json
  if isinstance(payload, dict) or isinstance(payload, list):
    payload = json.dumps(payload)
  self.Write(str(type) + payload)
}

Method connect() [ Language = python ]
{
  msg = {
    "sid": self.sid,
    "upgrades": [],
    "pingTimeout": (self.pingTimeout),
    "pingInterval": (self.pingInterval),
  }
  self.send(0, msg)
}

Method readfd(timeout = 0) [ Language = python ]
{
import os
import select
max_read_bytes = 1024 * 20

(data_ready, _, _) = select.select([self.fd], [], [], timeout)
if not data_ready:
  return

output = os.read(self.fd, max_read_bytes).decode(
    errors="ignore"
)
return output
}

Method writefd(input) [ Language = python ]
{
import os
os.write(self.fd, input.encode())
}

Method start() [ Language = python ]
{
import iris
import pty
import subprocess

bin = iris.system.Util.BinaryDirectory() + "irisdb"
mgr = iris.system.Util.ManagerDirectory()
username = iris.system.Process.UserName()
namespace = iris.system.Process.NameSpace()
cmd = [bin, "-s", mgr]
#; cmd = ["sh", "-c", " ".join(cmd)]
#; cmd = ["bash"]

master_fd, slave_fd = pty.openpty()

proc = subprocess.Popen(
  cmd,
  stdin=slave_fd,
  stdout=slave_fd,
  stderr=slave_fd,
  close_fds=True,
  shell=True,
  start_new_session=True,
)

return master_fd, proc
}

}
