/*  Discord Trade Bridge
 *
 *  TCP client to the external Python discord_driver. Receives TRADE_READY
 *  events (with codes parsed off Klawf Cove DMs) and sends back per-trade
 *  results. Wire protocol: newline-delimited JSON, see discord_driver/switch_bridge.py.
 */

#ifndef PokemonAutomation_PokemonSV_DiscordTradeBridge_H
#define PokemonAutomation_PokemonSV_DiscordTradeBridge_H

#include <chrono>
#include <deque>
#include <mutex>
#include <condition_variable>
#include <optional>
#include <string>
#include "Common/Cpp/Sockets/ClientSocket.h"
#include "PokemonSV_DiscordTradeBot.h"

namespace PokemonAutomation{
namespace NintendoSwitch{
namespace PokemonSV{


class DiscordTradeBridge : private AbstractClientSocket::Listener{
public:
    DiscordTradeBridge(const std::string& host, uint16_t port);
    ~DiscordTradeBridge();

    //  Block until connected or until "timeout" elapses. Returns true on success.
    bool wait_until_connected(std::chrono::seconds timeout);

    //  Block until a TRADE_READY message arrives. Returns nullopt on timeout
    //  or shutdown. Thread-safe.
    std::optional<DiscordTradeRequest> wait_for_trade_ready(
        std::chrono::milliseconds timeout
    );

    void send_trade_complete(const std::string& set_id);
    void send_trade_failed(const std::string& set_id, const std::string& reason);
    void send_pong();

private:
    //  AbstractClientSocket::Listener
    void on_connect_finished(const std::string& error_message) override;
    void on_receive_data(const void* data, size_t bytes) override;

    void send_json_line(const std::string& json);
    void process_line(const std::string& line);

    ClientSocket m_socket;
    std::mutex m_mutex;
    std::condition_variable m_cv;
    std::string m_recv_buffer;
    std::deque<DiscordTradeRequest> m_pending;
    bool m_connected = false;
    bool m_shutdown = false;
};


}
}
}
#endif
