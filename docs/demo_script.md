# Demo Script

Framing:

```powershell
chatserver demo framing
chatserver demo unsafe-framing
```

Live chat:

```powershell
chatserver init-db --db chat.db
chatserver serve --db chat.db
chatclient connect --nick alice
chatclient connect --nick bob
```

Inside the clients:

```text
/join general
hello
/msg bob private hello
/history general 25
/rooms
/who general
```

Safe feature demos (each spins up an ephemeral server and tears it down):

```powershell
chatserver demo basic
chatserver demo slow-client
chatserver demo rate-limit
chatserver demo idle-timeout
chatserver demo db-writer
chatserver demo graceful-shutdown
chatserver demo all
```

Failure demos (each runs the broken pattern and prints the evidence next to the
safe behavior):

```powershell
chatserver demo unsafe-framing
chatserver demo unsafe-slow-client
chatserver demo unsafe-room-race
chatserver demo unsafe-db-blocking
chatserver demo unsafe-shutdown
```

Live admin (serve with `--admin-port`, then query the control socket):

```powershell
chatserver serve --db chat.db --admin-port 9001
chatserver admin stats --port 9001
chatserver admin clients --port 9001
chatserver admin queues --port 9001
chatserver admin cache --port 9001
chatserver admin evictions --port 9001
chatserver admin kick --nick ada --port 9001
chatserver admin broadcast --message "restart in 5 minutes" --port 9001
```

