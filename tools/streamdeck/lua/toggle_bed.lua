-- API Monkey "Action Lua Script" for the bed key: toggles it on the
-- panel and returns the Swedish state text ("På"/"Av"), which the key's
-- Response Mapping turns into the on/off icon.
local json = require("json")
local res = http.request({
  method = "POST",
  url = "http://192.168.150.33:8080/api/sockets/bed/toggle",
  timeout_seconds = 5,
})
local data = json.decode(res.body)
if res.status_code ~= 200 or data == nil then
  error("Panelen svarade " .. tostring(res.status_code) .. ": " .. tostring(res.body))
end
return data.text
