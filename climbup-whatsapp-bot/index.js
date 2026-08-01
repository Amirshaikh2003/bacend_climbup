const { makeWASocket, useMultiFileAuthState, DisconnectReason, downloadMediaMessage } = require('@whiskeysockets/baileys');
const pino = require('pino');
const express = require('express');
const qrcode = require('qrcode-terminal');
const httpModule = require('https'); 
const fs = require('fs');
require('dotenv').config({ path: '../.env' });

const app = express();
const port = 3000;

// The backend URL running on Render
const BACKEND_URL = "https://bacend-climbup.onrender.com/api/whatsapp/webhook";
const SUPABASE_URL = process.env.SUPABASE_URL || "https://jueoglgbseoxszygpjdb.supabase.co"; 
const SUPABASE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || process.env.SUPABASE_KEY;

let latestQR = null;
let sock;

async function connectToWhatsApp () {
    const { state, saveCreds } = await useMultiFileAuthState('auth_info_baileys');
    
    sock = makeWASocket({
        auth: state,
        printQRInTerminal: true,
        logger: pino({ level: 'silent' }),
        browser: ["ClimbUP Bot", "Chrome", "10.0.0"]
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        
        if (qr) {
            latestQR = qr;
            qrcode.generate(qr, { small: true });
            console.log("Please scan the QR code above!");
        }

        if (connection === 'close') {
            const shouldReconnect = lastDisconnect.error?.output?.statusCode !== DisconnectReason.loggedOut;
            console.log('Connection closed due to ', lastDisconnect.error, ', reconnecting ', shouldReconnect);
            
            if (shouldReconnect) {
                connectToWhatsApp();
            } else {
                console.log('Logged out. Please delete auth_info_baileys folder and restart to scan again.');
            }
        } else if (connection === 'open') {
            console.log('✅ WhatsApp Bot is Ready and Connected using Baileys!');
            latestQR = null; // Clear QR code as we are connected
        }
    });

    sock.ev.on('messages.upsert', async m => {
        const msg = m.messages[0];
        
        // Ignore messages from ourselves, if there's no message, or if it's from a group
        if (!msg.message || msg.key.fromMe) return;
        
        const senderId = msg.key.remoteJid;
        if (senderId.includes('@g.us')) {
            return; // Ignore group messages
        }

        const senderNumber = senderId.split('@')[0];
        console.log(`📩 Received message from ${senderNumber}`);

        const messageType = Object.keys(msg.message)[0];
        
        try {
            if (messageType === 'conversation' || messageType === 'extendedTextMessage') {
                const text = msg.message.conversation || msg.message.extendedTextMessage?.text;
                console.log(`Text: ${text}`);

                // Send to Python webhook
                await sendToWebhook({
                    sender_number: senderNumber,
                    message: text || "",
                    has_media: false
                }, senderId);

            } else if (messageType === 'documentMessage' || messageType === 'documentWithCaptionMessage' || messageType === 'imageMessage') {
                const docMsg = msg.message.documentMessage || msg.message.documentWithCaptionMessage?.message?.documentMessage || msg.message.imageMessage;
                const caption = docMsg?.caption || msg.message.documentWithCaptionMessage?.message?.documentMessage?.caption || msg.message.imageMessage?.caption || "";
                console.log(`Media received. Mime: ${docMsg?.mimetype} | Caption: ${caption}`);

                const allowedTypes = ['application/pdf', 'image/jpeg', 'image/png', 'image/webp'];
                if (!allowedTypes.includes(docMsg?.mimetype)) {
                    await sock.sendMessage(senderId, { text: "❌ Sorry, I only accept PDFs and Images!" });
                    return;
                }

                // Download media
                const buffer = await downloadMediaMessage(
                    msg,
                    'buffer',
                    { },
                    { 
                        logger: pino({ level: 'silent' }),
                        reuploadRequest: sock.updateMediaMessage
                    }
                );
                
                const base64Data = buffer.toString('base64');
                console.log("Media downloaded and converted to base64 successfully.");

                const filename = docMsg?.fileName || (docMsg?.mimetype === 'application/pdf' ? 'document.pdf' : 'image.jpg');

                await sendToWebhook({
                    sender_number: senderNumber,
                    message: caption,
                    has_media: true,
                    base64_media: base64Data,
                    mime_type: docMsg?.mimetype || "application/pdf",
                    filename: filename
                }, senderId);
            } else {
                await sock.sendMessage(senderId, { text: "Please send a valid PDF, Image, or a `#CLIMBXXXX` code." });
            }
        } catch (error) {
            console.error("Error processing message:", error);
            await sock.sendMessage(senderId, { text: "❌ Oops! Something went wrong while processing your message." });
        }
    });
}

async function sendToWebhook(payload, senderId) {
    const payloadString = JSON.stringify(payload);

    const url = new URL(BACKEND_URL);
    const options = {
        hostname: url.hostname,
        path: url.pathname,
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(payloadString)
        }
    };

    const req = httpModule.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', async () => {
            console.log(`Webhook response status: ${res.statusCode}`);
            console.log(`Webhook response body: ${data}`);
            
            try {
                // If it's a JSON response, parse it.
                let replyText = data;
                try {
                    const jsonData = JSON.parse(data);
                    if (jsonData.reply) {
                        replyText = jsonData.reply;
                    } else if (jsonData.message) {
                        replyText = jsonData.message;
                    }
                } catch(e) {}
                
                await sock.sendMessage(senderId, { text: replyText });
            } catch (err) {
                console.error("Failed to send reply to user:", err);
            }
        });
    });

    req.on('error', async (error) => {
        console.error("Webhook request failed:", error);
        await sock.sendMessage(senderId, { text: "❌ The backend server is currently unreachable. Please try again later." });
    });

    req.write(payloadString);
    req.end();
}

// Polling function for OTPs
async function pollForPendingOTPs() {
    if (!SUPABASE_KEY || !sock) return;

    try {
        const url = new URL(`${SUPABASE_URL}/rest/v1/whatsapp_links?status=eq.pending_otp`);
        const options = {
            hostname: url.hostname,
            path: url.pathname + url.search,
            method: 'GET',
            headers: {
                'apikey': SUPABASE_KEY,
                'Authorization': `Bearer ${SUPABASE_KEY}`
            }
        };

        const req = httpModule.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => { data += chunk; });
            res.on('end', async () => {
                if (res.statusCode === 200 && data) {
                    try {
                        const pendingLinks = JSON.parse(data);
                        for (const link of pendingLinks) {
                            if (link.target_number && link.code) {
                                // 1. Send WhatsApp Message
                                const jid = `${link.target_number}@s.whatsapp.net`;
                                await sock.sendMessage(jid, { 
                                    text: `Hi there! 👋\n\nYour ClimbUP Verification OTP is: *${link.code}*\n\nPlease enter this on the portal to securely connect your account.` 
                                });
                                console.log(`OTP Sent to ${link.target_number}`);

                                // 2. Mark as sent in DB
                                const updateOptions = {
                                    hostname: url.hostname,
                                    path: `/rest/v1/whatsapp_links?code=eq.${link.code}`,
                                    method: 'PATCH',
                                    headers: {
                                        'apikey': SUPABASE_KEY,
                                        'Authorization': `Bearer ${SUPABASE_KEY}`,
                                        'Content-Type': 'application/json'
                                    }
                                };
                                const patchReq = httpModule.request(updateOptions, (patchRes) => {
                                    // ignore patch response for now
                                });
                                patchReq.write(JSON.stringify({ status: 'otp_sent' }));
                                patchReq.end();
                            }
                        }
                    } catch(e) {
                        console.error("Error processing pending OTPs:", e);
                    }
                }
            });
        });
        req.on('error', (e) => console.error("OTP Poll Error:", e));
        req.end();
    } catch (e) {
        console.error(e);
    }
}

// Start connection
connectToWhatsApp();

// Start OTP polling every 3 seconds
setInterval(pollForPendingOTPs, 3000);

app.listen(port, () => {
    console.log(`Dummy server listening on port ${port} to keep Render happy`);
});
