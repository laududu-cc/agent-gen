const express = require('express');
const cors = require('cors');
const { OpenAI } = require('openai');
const path = require('path');

const app = express();
app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// DeepSeek API Configuration
const openai = new OpenAI({
    baseURL: 'https://api.deepseek.com',
    apiKey: 'sk-40fd6accfead48d8a3941fd8592efa17'
});

// Endpoint for creating an agent
app.post('/api/create-agent', async (req, res) => {
    try {
        const { messages, stream } = req.body;
        
        const creatorSystemPrompt = `
You are AgentForge (智戎), an AI that helps users create their own custom AI assistants.
The user will describe the assistant they want to create.
If the user's description is vague or missing key details (like tone, specific tasks), ask 1-2 clarifying questions in Chinese.
If the description is clear and sufficient, reply to the user confirming the creation, and AT THE VERY END of your response, you MUST output the following exact XML block containing the configuration:
<AGENT_READY>
<NAME>Name of the agent</NAME>
<PROMPT>The complete, detailed system prompt for the new agent, instructing it how to behave</PROMPT>
</AGENT_READY>
`;

        const response = await openai.chat.completions.create({
            model: "deepseek-chat",
            messages: [
                { role: "system", content: creatorSystemPrompt },
                ...messages
            ],
            stream: stream === true
        });

        if (stream) {
            res.setHeader('Content-Type', 'text/event-stream');
            res.setHeader('Cache-Control', 'no-cache');
            res.setHeader('Connection', 'keep-alive');

            for await (const chunk of response) {
                const content = chunk.choices[0]?.delta?.content || '';
                if (content) {
                    res.write(`data: ${JSON.stringify({ content })}\n\n`);
                }
            }
            res.write('data: [DONE]\n\n');
            res.end();
        } else {
            res.json({ message: response.choices[0].message.content });
        }
    } catch (error) {
        console.error('Error in create-agent:', error);
        res.status(500).json({ error: 'Failed to process creation request' });
    }
});

// Endpoint for testing the agent
app.post('/api/chat', async (req, res) => {
    try {
        const { systemPrompt, messages, stream } = req.body;

        const messagesToSend = [];
        if (systemPrompt && typeof systemPrompt === 'string') {
            messagesToSend.push({ role: "system", content: systemPrompt });
        }

        const response = await openai.chat.completions.create({
            model: "deepseek-chat",
            messages: [
                ...messagesToSend,
                ...messages
            ],
            stream: stream === true
        });

        if (stream) {
            res.setHeader('Content-Type', 'text/event-stream');
            res.setHeader('Cache-Control', 'no-cache');
            res.setHeader('Connection', 'keep-alive');

            for await (const chunk of response) {
                const content = chunk.choices[0]?.delta?.content || '';
                if (content) {
                    res.write(`data: ${JSON.stringify({ content })}\n\n`);
                }
            }
            res.write('data: [DONE]\n\n');
            res.end();
        } else {
            res.json({
                message: response.choices[0].message.content
            });
        }
    } catch (error) {
        console.error('Error in chat:', error);
        res.status(500).json({ error: 'Failed to process chat request' });
    }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
    console.log(`AgentForge Server is running on http://localhost:${PORT}`);
});
