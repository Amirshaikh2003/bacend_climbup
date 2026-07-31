const express = require('express');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const fs = require('fs');
const http = require('http'); // Use 'https' if your Render server uses HTTPS

// Configuration
// We point this to your Render.com backend URL in production, or localhost during testing.
const BACKEND_URL = process.env.BACKEND_URL || 'https://bacend-climbup.onrender.com/api/whatsapp/webhook';
const PORT = process.env.PORT || 3000;

// Setup Dummy Express Server for Render Web Service Health Checks
const app = express();
app.get('/', (req, res) => res.send('ClimbUP WhatsApp Bot is running!'));
app.listen(PORT, () => console.log(`Dummy server listening on port ${PORT} to keep Render happy`));

// Initialize Client with LocalAuth to persist session across restarts
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

client.on('qr', (qr) => {
    // Generate and scan this code with your spare phone
    console.log("Please SCAN the QR code below with your WhatsApp to start the Bot:");
    qrcode.generate(qr, { small: true });
});

client.on('ready', () => {
    console.log('✅ WhatsApp Bot is Ready and Connected!');
});

client.on('message', async (msg) => {
    console.log(`[Message Received] From: ${msg.from} | Type: ${msg.type}`);
    
    // We only process text or pdfs (documents)
    if (msg.type !== 'chat' && msg.type !== 'document') {
        return;
    }

    try {
        let hasMedia = msg.hasMedia;
        let base64Media = null;
        let mimeType = null;
        let filename = null;

        if (hasMedia && msg.type === 'document') {
            const media = await msg.downloadMedia();
            if (media.mimetype === 'application/pdf') {
                base64Media = media.data;
                mimeType = media.mimetype;
                filename = media.filename || "document.pdf";
            } else {
                return msg.reply("❌ I only accept PDF files.");
            }
        }

        // Send payload to Python FastAPI backend
        const payload = JSON.stringify({
            message: msg.body,
            sender_number: msg.from,
            has_media: hasMedia && base64Media !== null,
            base64_media: base64Media,
            mime_type: mimeType,
            filename: filename
        });

        const httpModule = BACKEND_URL.startsWith('https') ? require('https') : require('http');

        const req = httpModule.request(BACKEND_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(payload)
            }
        }, (res) => {
            let responseData = '';
            res.on('data', chunk => responseData += chunk);
            res.on('end', () => {
                if (res.statusCode === 200) {
                    try {
                        const jsonResponse = JSON.parse(responseData);
                        if (jsonResponse.reply) {
                            msg.reply(jsonResponse.reply);
                        }
                    } catch (e) {
                        console.error("Error parsing backend JSON:", e);
                    }
                } else {
                    console.error("Backend error:", responseData);
                    msg.reply("❌ Error talking to server. Please try again later.");
                }
            });
        });

        req.on('error', (e) => {
            console.error(`Problem with request: ${e.message}`);
            msg.reply("❌ Backend Server is unreachable.");
        });

        req.write(payload);
        req.end();

    } catch (error) {
        console.error("Error processing message:", error);
    }
});

client.initialize();
