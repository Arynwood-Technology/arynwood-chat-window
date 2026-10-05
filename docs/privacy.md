# Privacy

## What is kept, and for how long

Each question gets one row in the chat log (`<data dir>/chats.sqlite`), holding:

- the question and the answer;
- the pages shown as sources;
- the time, and the outcome (answered, not covered, rate limited, busy, error, cancelled);
- the model, and how long the answer took;
- a **visitor hash**: an HMAC of the visitor's address and the site id, keyed by `CHAT_WINDOW_SECRET`. It lets
  you see that one address sent 500 questions without storing the address.

Rows older than the site's `retention_days` (default 30) are deleted every hour, and `chat-window purge`
deletes them on demand.

## What isn't kept

- **Addresses.** Raw IP addresses, cookies and user agents aren't stored. The rate limiter holds addresses
  in memory for at most a day, and a restart clears them.
- **Conversations.** A conversation's turns are held in memory for 30 minutes so follow-up questions make
  sense, then dropped.
- **Personal details** in the log are only what visitors type into the chat.

## Deleting a chat

"Delete this chat" in the window removes that chat's rows from the log immediately, and its turns from
memory. The chat's id lives only in the browser tab (`sessionStorage`), so only that tab can delete it.

## The hash and the secret

The visitor hash is keyed per site, so the same visitor can't be linked across two sites. Anyone holding the
secret could test every possible IPv4 address against a hash, so keep `CHAT_WINDOW_SECRET` out of backups you
share and out of version control. Changing it breaks the link to older rows, which is fine.

## Review and training

`chat-window export SITE` writes answered and not-covered chats as JSONL for review. It drops the visitor
hash and session id, and replaces email addresses, phone numbers, IP addresses and long token-like strings.
The redaction catches the obvious, not everything: read the export before any of it goes into a training set.

## What the site owner should do

- **Privacy policy.** Say in your privacy policy that the chat exists, what it keeps, for how long, and why
  (security, monitoring, improving the assistant). The chat window's notice links to `privacy_url`.
- **Notice.** If you change `retention_days` or the purposes, update the notice (`notice` in the site file)
  to match.
- **Personal data law.** If your visitors include people covered by personal-data law (the EU's GDPR, for
  example), you are the controller of this log, and the legal basis and visitor requests are yours to handle.
  Deleting by chat (above) and the short retention help.
