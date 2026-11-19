# Access SelfX on a VPS

Install SelfX on Ubuntu 24.04 using the [native setup guide](../docs/SELF_HOSTING.md#ubuntu-2404). The default listener is `127.0.0.1:8800` on the VPS. An SSH tunnel lets you open it from your own browser without a domain or a public SelfX port.

1. Verify that you can sign in to the VPS over SSH. Keep your provider’s firewall restricted to the SSH access you need. Leave the SelfX, PostgreSQL, Redis, and Ollama ports private.
2. From your own computer, open a terminal and run the command below, substituting your SSH account and server address. The second `8800` is the port you chose on the VPS. Change the first `8800` if a different app already uses that port on your computer.

   ```sh
   ssh -NT -o ExitOnForwardFailure=yes -L 127.0.0.1:8800:127.0.0.1:8800 account@your-server
   ```

3. Keep the SSH session open and visit [http://127.0.0.1:8800](http://127.0.0.1:8800). Sign into SelfX with your bootstrap administrator account. Close the terminal when you are done.

SSH encrypts traffic along the network path between your computer and the VPS. Both HTTP listeners in this example are on loopback. [OpenSSH port forwarding](https://man.openbsd.org/ssh#L)

If the browser cannot reach SelfX, first run `curl -fsS http://127.0.0.1:8800/api/v1/healthz` on the VPS using the port you installed. If the health check passes and SSH reports “administratively prohibited,” ask your VPS administrator whether local forwarding is allowed for your account. See [service checks](../docs/SELF_HOSTING.md#service-checks) for a failed health check.

For a shared deployment, keep SelfX behind an access-controlled private network or reverse proxy and terminate HTTPS at the proxy. Keep the frontend and `/api` on the same origin. Review access, upload limits, retention, and resource capacity before inviting other users.
