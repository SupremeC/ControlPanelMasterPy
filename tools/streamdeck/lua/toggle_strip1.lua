-- API Monkey "Action Lua Script" for the strip 1 key: toggles the
-- segment and returns "true"/"false", which the key's Response Mapping
-- turns into the on/off icon (same values as the polled
-- strips.segments.1.on).
local json = require("json")
local res = http.request({
  method = "POST",
  url = "http://192.168.150.33:8080/api/strips/1/toggle",
  timeout_seconds = 5,
})
local data = json.decode(res.body)
if res.status_code ~= 200 or data == nil then
  error("Panelen svarade " .. tostring(res.status_code) .. ": " .. tostring(res.body))
end
if data.on == nil then return "okand" end
return tostring(data.on)
