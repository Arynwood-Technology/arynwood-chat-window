<?php
/*
 * Arynwood Chat Window embed for PHP sites. Include it before </body> on the pages that show the chat:
 *
 *     <?php $chatWindowNonce = $cspNonce; include __DIR__ . '/chat-window-embed.php'; ?>
 *
 * $chatWindowNonce must be the nonce this request's Content-Security-Policy header carries. A CSP with
 * 'strict-dynamic' runs only scripts with that nonce; without a nonce-based CSP, leave it unset.
 */
$chatWindowSrc   = $chatWindowSrc   ?? '/chat-window/chat-window.js';   // or https://chat.example.com/chat-window.js
$chatWindowSite  = $chatWindowSite  ?? 'mysite';                        // the site file's name, without .toml
$chatWindowAttrs = $chatWindowAttrs ?? [];                              // e.g. ['data-accent' => '#1f4e79']
$chatWindowNonce = $chatWindowNonce ?? null;

$attrs = ['src' => $chatWindowSrc, 'data-site' => $chatWindowSite] + $chatWindowAttrs;
if ($chatWindowNonce) {
    $attrs['nonce'] = $chatWindowNonce;
}
$html = '';
foreach ($attrs as $name => $value) {
    $html .= ' ' . htmlspecialchars((string) $name, ENT_QUOTES) . '="' . htmlspecialchars((string) $value, ENT_QUOTES) . '"';
}
echo '<script' . $html . ' defer></script>' . "\n";
