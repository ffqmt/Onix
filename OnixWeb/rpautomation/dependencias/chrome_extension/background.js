chrome.webRequest.onBeforeSendHeaders.addListener(
    function(details) {
        var newHeaders = details.requestHeaders;
        for (var i = 0; i < newHeaders.length; ++i) {
            if (newHeaders[i].name === 'User-Agent') {
                newHeaders[i].value = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36";
                break;
            }
        }
        return {requestHeaders: newHeaders};
    },
    {urls: ["<all_urls>"]},
    ["blocking", "requestHeaders"]
);
