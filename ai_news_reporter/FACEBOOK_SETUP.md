# Facebook Posting Integration

This AI News Reporter now supports posting to Facebook Pages in addition to LinkedIn.

## Setup Instructions

### 1. Get Facebook Page Access Token

1. Go to [Facebook Developers](https://developers.facebook.com/)
2. Create an App (if you don't have one)
3. Add the Pages product to your app
4. Generate a Page Access Token:
   - Go to your App → Tools → Graph API Explorer
   - Select your app and page
   - Generate a token with `pages_manage_posts` and `pages_read_user` permissions
5. Copy the access token

### 2. Get Your Facebook Page ID

1. Visit your Facebook Page
2. Go to Settings → About → Check the URL
3. Your Page ID is the numeric part in the URL
4. Alternatively, use the Graph API: `https://graph.facebook.com/me/accounts?access_token=YOUR_TOKEN`

### 3. Configure Environment Variables

Update your `.env` file with:

```env
FACEBOOK_PAGE_ACCESS_TOKEN=your_access_token_here
FACEBOOK_PAGE_ID=your_page_id_here
```

## Usage

Users can now request posts to Facebook in several ways:

### Post Direct Content to Facebook
```
"Post this to Facebook: Check out our latest updates!"
```

### Find News and Post to Facebook
```
"Find AI news and post it on Facebook"
"Search for blockchain news and post on Facebook"
```

### The system will detect "facebook", "fb", or "meta" in requests and route accordingly

## API Reference

### Facebook Agent

The FacebookAgent class handles posting to Facebook:

```python
from agents.facebook_agent import FacebookAgent

result = await FacebookAgent.post(content)
# Returns: {"success": True, "post_id": "..."} or {"success": False, "error": "..."}
```

### Facebook Service

The FacebookService provides low-level API operations:

```python
from services.facebook_service import FacebookService

# Create a post
result = await FacebookService.create_post(
    content="Your post content here"
)

# Verify page access
info = await FacebookService.get_page_info(page_id, access_token)
```

## Features

- ✅ Auto-detect Facebook requests (mentions of "facebook", "fb", "meta")
- ✅ Automatic retry logic with exponential backoff
- ✅ Rate limiting (60 seconds between posts)
- ✅ Error handling and validation
- ✅ Async/await support
- ✅ Integration with news search and summarization pipeline

## Workflow Integration

The Facebook agent is fully integrated into the LangGraph workflow:

1. **Intent Classification**: Detects if user wants to post to Facebook or LinkedIn
2. **News Retrieval**: Searches for relevant news (optional)
3. **Summarization**: Creates summaries of articles (optional)
4. **Confirmation**: Awaits user approval before posting (for news_then_post)
5. **Formatting**: Formats content for the target platform
6. **Posting**: Posts to Facebook or LinkedIn
7. **Storage**: Stores results in MongoDB

## Error Handling

The system gracefully handles:
- Missing or invalid access tokens
- Network errors (with retry logic)
- API rate limiting (429 status)
- Invalid page IDs
- Server errors (5xx)

## Example Conversation

```
User: "Find the latest AI news and post it on Facebook"

Bot Creates Plan:
1. Identify intent: news_then_post → Facebook
2. Search for AI news
3. Filter for tech/AI related articles
4. Summarize top 3 articles
5. Ask for confirmation
6. Format for Facebook (using Meta Graph API v20.0)
7. Post to your Facebook page
8. Return the posted content and confirmation

Bot: "🔍 Here's what I found — shall I post this to Facebook?"
[Shows preview of articles and summaries]

User: "yes"

Bot: ✅ Posted successfully to Facebook!
```

## Supported Intents

- `news_query`: Search tech news and return summaries
- `post_request`: Post directly to specified platform (Facebook/LinkedIn)
- `news_then_post`: Search news, summarize, and post to specified platform
- `other`: Any unrecognized request

## Facebook API Version

The integration uses Meta Graph API v20.0.
For the latest API documentation, visit: https://developers.facebook.com/docs/graph-api
