(function () {
    window.toggleCardDim = function (checkbox) {
        const wrapper = checkbox.closest('.video-card-wrapper, .channel-card-wrapper');
        if (wrapper) wrapper.classList.toggle('is-chat-disabled', !checkbox.checked);
    };
})();
