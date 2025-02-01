function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function syncToken(coinId) {
    const csrftoken = getCookie('csrftoken');
    
    // 显示加载状态
    const button = event.target;
    const originalText = button.innerText;
    button.innerText = '同步中...';
    button.disabled = true;

    fetch(`/admin/wallet/tokenindex/${coinId}/sync/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrftoken,
            'Content-Type': 'application/json',
        },
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            // 更新成功后刷新页面
            window.location.reload();
        } else {
            // 显示错误信息
            alert('同步失败: ' + data.message);
            button.innerText = originalText;
            button.disabled = false;
        }
    })
    .catch(error => {
        alert('同步失败: ' + error);
        button.innerText = originalText;
        button.disabled = false;
    });
} 