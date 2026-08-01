const { makeWASocket, useMultiFileAuthState, DisconnectReason, downloadMediaMessage } = require('@whiskeysockets/baileys');
const pino = require('pino');
const express = require('express');
const qrcode = require('qrcode-terminal');
const httpModule = require('https'); 
const fs = require('fs');

const app = express();
const port = 3000;

// The backend URL running on Render
const BACKEND_URL = "https://bacend-climbup.onrender.com/api/whatsapp/webhook";

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
        
        // Ignore messages from ourselves or if there's no message
        if (!msg.message || msg.key.fromMe) return;

        const senderId = msg.key.remoteJid;
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

            } else if (messageType === 'documentMessage' || messageType === 'documentWithCaptionMessage') {
                const docMsg = msg.message.documentMessage || msg.message.documentWithCaptionMessage.message.documentMessage;
                console.log(`Document received: ${docMsg.fileName}`);

                if (docMsg.mimetype !== 'application/pdf') {
                    await sock.sendMessage(senderId, { text: "❌ Sorry, I only accept PDF files!" });
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
                console.log("PDF downloaded and converted to base64 successfully.");

                // Send to Python webhook
                await sendToWebhook({
                    sender_number: senderNumber,
                    message: "",
                    has_media: true,
                    media_data: base64Data,
                    media_mime_type: "application/pdf",
                    media_filename: docMsg.fileName || "document.pdf"
                }, senderId);
            } else {
                await sock.sendMessage(senderId, { text: "Please send a valid PDF document or a `#CLIMBXXXX` code." });
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
            
            try {
                // If it's a JSON response, parse it.
                let replyText = data;
                try {
                    const jsonData = JSON.parse(data);
                    if (jsonData.message) {
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

// Start connection
connectToWhatsApp();

app.listen(port, () => {
    console.log(`Dummy server listening on port ${port} to keep Render happy`);
});
