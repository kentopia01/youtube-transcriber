# User Guide (Nontechnical)

This guide is for people who want to use the app without dealing with code.

## What This App Helps You Do

- Turn YouTube videos into text transcripts
- Get a summary of each video
- Search across video content using natural language
- Process many videos from a channel

## Before You Start

Ask your technical admin to confirm:

- The app is running and accessible in your browser
- Background workers are running
- Required API keys are configured

If those are ready, open the app home page (for example: `http://localhost:8000`).

## 1. Submit a Single Video

1. Go to **Submit** page.
2. Paste a YouTube video URL.
3. Click submit.
4. You’ll get a job ID and the video enters the processing queue.

What happens next:

- Audio is downloaded
- Speech is transcribed
- A summary is generated
- Search embeddings are created

## 2. Submit a Channel

1. On the **Submit** page, paste a YouTube channel URL.
2. The app discovers available videos.
3. Select the videos you want to process.
4. Start processing.

Notes:

- Large selections are processed in batches.
- You can monitor progress in the **Queue** page.

## 3. Monitor Progress

Go to **Queue** to check jobs.

Job statuses you may see:

- `queued`: waiting to start
- `running`: currently processing
- `completed`: finished successfully
- `failed`: stopped with an error

If a job fails, open job details and copy the error message for support.

## 4. Read Results

Go to **Videos** and open a processed video.

You can view:

- Video metadata
- Full transcript segments with timestamps
- Generated summary

## 5. Search Across Content

1. Open **Search**.
2. Enter a question or topic (example: `pricing strategy`, `security incidents`, `AI roadmap`).
3. Review matching transcript chunks and jump to related videos.

## Common Problems and What to Do

- URL rejected:
  - Make sure it is a YouTube video or channel link.
- Job stuck in `queued`:
  - Workers may be down. Contact admin.
- Search returns no results:
  - The video may not be fully processed yet.
- Job shows `failed`:
  - Open the job detail page and send the error message to support.

## Best Practices

- Start with a few videos first to validate output quality.
- Use channel processing for bulk workflows.
- Re-check the Queue page for failures after large submissions.
- Use short, clear search queries first, then refine.

## Need Technical Details?

- Return to the project docs hub: [`../README.md`](../README.md)
