/*  Discord Trade Bridge */

#include <cstring>
#include "CommonFramework/Tools/GlobalThreadPools.h"
#include "PokemonSV_DiscordTradeBridge.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonSV{


//  Minimal hand-rolled JSON parsing. The wire protocol is fully under our control
//  and uses only flat objects with string values, so we don't need a real parser.
//  Format (one per line):
//    {"type":"TRADE_READY","code":"12345678","set_id":"abc"}
//    {"type":"TRADE_CANCELLED","set_id":"abc","reason":"..."}
//    {"type":"PING"}
static std::string extract_string_field(const std::string& json, const std::string& key){
    std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return {};
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return {};
    pos = json.find('"', pos);
    if (pos == std::string::npos) return {};
    size_t end = json.find('"', pos + 1);
    if (end == std::string::npos) return {};
    return json.substr(pos + 1, end - pos - 1);
}

//  Extract a bare numeric (no surrounding quotes) field. Returns `default_value`
//  if the key is missing or the value isn't a non-negative integer.
static int extract_int_field(const std::string& json, const std::string& key, int default_value){
    std::string needle = "\"" + key + "\"";
    size_t pos = json.find(needle);
    if (pos == std::string::npos) return default_value;
    pos = json.find(':', pos + needle.size());
    if (pos == std::string::npos) return default_value;
    pos++;
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) pos++;
    if (pos >= json.size() || !(json[pos] >= '0' && json[pos] <= '9')) return default_value;
    int value = 0;
    while (pos < json.size() && json[pos] >= '0' && json[pos] <= '9'){
        value = value * 10 + (json[pos] - '0');
        pos++;
    }
    return value;
}

static std::string escape_json(const std::string& s){
    std::string out;
    out.reserve(s.size() + 2);
    for (char c : s){
        switch (c){
        case '"':  out += "\\\""; break;
        case '\\': out += "\\\\"; break;
        case '\n': out += "\\n"; break;
        case '\r': out += "\\r"; break;
        case '\t': out += "\\t"; break;
        default:
            if (static_cast<unsigned char>(c) < 0x20){
                char buf[8];
                std::snprintf(buf, sizeof(buf), "\\u%04x", c);
                out += buf;
            } else {
                out += c;
            }
        }
    }
    return out;
}


DiscordTradeBridge::DiscordTradeBridge(const std::string& host, uint16_t port)
    : m_socket(GlobalThreadPools::unlimited_realtime())
{
    m_socket.add_listener(*this);
    m_socket.connect(host, port);
}

DiscordTradeBridge::~DiscordTradeBridge(){
    {
        std::lock_guard<std::mutex> lk(m_mutex);
        m_shutdown = true;
    }
    m_cv.notify_all();
    m_socket.close();
}

bool DiscordTradeBridge::wait_until_connected(std::chrono::seconds timeout){
    std::unique_lock<std::mutex> lk(m_mutex);
    return m_cv.wait_for(lk, timeout, [&]{ return m_connected || m_shutdown; })
        && m_connected;
}

std::optional<DiscordTradeRequest> DiscordTradeBridge::wait_for_trade_ready(
    std::chrono::milliseconds timeout
){
    std::unique_lock<std::mutex> lk(m_mutex);
    m_cv.wait_for(lk, timeout, [&]{ return !m_pending.empty() || m_shutdown; });
    if (m_pending.empty()) return std::nullopt;
    DiscordTradeRequest req = std::move(m_pending.front());
    m_pending.pop_front();
    return req;
}

bool DiscordTradeBridge::wait_for_next_trade_ready(std::chrono::milliseconds timeout){
    std::unique_lock<std::mutex> lk(m_mutex);
    m_cv.wait_for(lk, timeout, [&]{ return m_next_trade_ready_count > 0 || m_shutdown; });
    if (m_next_trade_ready_count <= 0) return false;
    m_next_trade_ready_count--;
    return true;
}

void DiscordTradeBridge::send_trade_complete(const std::string& set_id){
    send_json_line(
        "{\"type\":\"TRADE_COMPLETE\",\"set_id\":\"" + escape_json(set_id) + "\"}"
    );
}

void DiscordTradeBridge::send_trade_failed(
    const std::string& set_id, const std::string& reason
){
    send_json_line(
        "{\"type\":\"TRADE_FAILED\",\"set_id\":\"" + escape_json(set_id)
        + "\",\"reason\":\"" + escape_json(reason) + "\"}"
    );
}

void DiscordTradeBridge::send_pong(){
    send_json_line("{\"type\":\"PONG\"}");
}

void DiscordTradeBridge::send_json_line(const std::string& json){
    std::string line = json + "\n";
    m_socket.send(line.data(), line.size());
}

void DiscordTradeBridge::on_connect_finished(const std::string& error_message){
    {
        std::lock_guard<std::mutex> lk(m_mutex);
        m_connected = error_message.empty();
    }
    m_cv.notify_all();
    if (error_message.empty()){
        send_json_line("{\"type\":\"READY\"}");
    }
}

void DiscordTradeBridge::on_receive_data(const void* data, size_t bytes){
    std::lock_guard<std::mutex> lk(m_mutex);
    m_recv_buffer.append(static_cast<const char*>(data), bytes);
    size_t nl;
    while ((nl = m_recv_buffer.find('\n')) != std::string::npos){
        std::string line = m_recv_buffer.substr(0, nl);
        m_recv_buffer.erase(0, nl + 1);
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (!line.empty()){
            process_line(line);
        }
    }
}

void DiscordTradeBridge::process_line(const std::string& line){
    //  Caller already holds m_mutex.
    std::string type = extract_string_field(line, "type");
    if (type == "TRADE_READY"){
        DiscordTradeRequest req;
        req.code = extract_string_field(line, "code");
        req.set_id = extract_string_field(line, "set_id");
        req.batch_size = extract_int_field(line, "batch_size", 1);
        if (req.batch_size < 1) req.batch_size = 1;
        if (!req.code.empty() && !req.set_id.empty()){
            m_pending.push_back(std::move(req));
            m_cv.notify_all();
        }
    } else if (type == "NEXT_TRADE_READY"){
        m_next_trade_ready_count++;
        m_cv.notify_all();
    }
    //  PING / TRADE_CANCELLED handling deliberately omitted for v1 — Python
    //  side currently only sends TRADE_READY at runtime.
}


}
}
}
