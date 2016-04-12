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


--TODO: Consider adding a password option. Maybe it would be there if a password file existed.

ipCfg = {
	ip 		= "192.168.4.1",
	netmask	= "255.255.255.0",
	gateway	= "192.168.4.1"
}
apCfg = {
	ssid = "Firmware Setup",
	pwd  = "123456789",
}
wifi.setmode(wifi.SOFTAP)
wifi.ap.config(apCfg)
wifi.ap.setip(ipCfg)

tmr.alarm(0, 1000, 1, function()
	 if wifi.ap.getip() ~= nil then
		ip, netmask, gateway = wifi.ap.getip()
		tmr.stop(0)
	 end
end)

--Set up the server to receive files and do anything else.
local srv = net.createServer(net.TCP, 600)

connectionCount = 0  -- Keep track of how many connections we have.
srv:listen(23, function(conn)
	connectionCount = connectionCount + 1
	if connectionCount > 1 then
		--We already have a connection. We don't support more than
		-- one connection because of the way we output data.
		conn:send("Too many connections!")
		conn:close()
	end
	conn:send("Firmware Upgrader\n\r")
	node.output(function(str)
		if conn then
			conn:send(str)
		end
	end, 0)

	conn:on("receive",function(conn, payload)
		node.input(payload)
	end)

	conn:on("disconnection",function(conn)
		connectionCount = connectionCount - 1
		node.output(nil)
	end)
end)