const express = require('express');
const { Client, LocalAuth, MessageMedia } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const fs = require('fs');
const http = require('http'); // Use 'https' if your Render server uses HTTPS

// Configuration
// We point this to your Render.com backend URL in production, or localhost during testing.
const BACKEND_URL = process.env.BACKEND_URL || 'https://bacend-climbup.onrender.com/api/whatsapp/webhook';
const PORT = process.env.PORT || 3000;

let latestQR = null;

// Setup Dummy Express Server for Render Web Service Health Checks and QR Scanning
const app = express();

app.get('/', (req, res) => res.send('ClimbUP WhatsApp Bot is running!'));

app.get('/qr', (req, res) => {
    if (!latestQR) {
        return res.send('<h3>No QR code available right now. Maybe it is already connected?</h3>');
    }
    // Generate a beautiful scannable QR code image using a free API
    const qrImageUrl = `https://api.qrserver.com/v1/create-qr-code/?size=400x400&data=${encodeURIComponent(latestQR)}`;
    res.send(`
        <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; font-family:sans-serif;">
            <h2>Scan this QR code with your Bot's WhatsApp</h2>
            <img src="${qrImageUrl}" alt="WhatsApp QR Code" style="border: 2px solid black; padding: 10px; border-radius: 10px;" />
            <p style="color:gray;">This code refreshes automatically. Refresh this page if it expires.</p>
        </div>
    `);
});

app.listen(PORT, () => console.log(`Dummy server listening on port ${PORT} to keep Render happy`));

// Initialize Client with LocalAuth to persist session across restarts
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: {
        headless: true,
        args: [
            '--no-sandbox', 
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--single-process', // Crucial for Render Free Tier (saves memory)
            '--disable-gpu'
        ]
    },
    // Force a specific working WhatsApp Web version to prevent "Couldn't link device" errors
    webVersionCache: {
        type: 'remote',
        remotePath: 'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/2.2412.54.html',
    }
});

client.on('qr', (qr) => {
    latestQR = qr;
    console.log("Please visit https://climbup-whatsapp-bot.onrender.com/qr in your browser to scan the QR easily!");
    // Also print to terminal just in case
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
