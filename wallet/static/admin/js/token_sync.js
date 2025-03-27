(function($) {
    $(document).ready(function() {
        // 等待 DOM 完全加载
        setTimeout(function() {
            // 添加同步按钮到地址字段后
            const addressField = $('#id_address');
            if (addressField.length) {
                const syncButton = $('<button/>', {
                    type: 'button',
                    class: 'sync-button',
                    text: '同步元数据'
                });
                
                // 确保按钮被正确插入
                addressField.after(syncButton);
                
                // 处理同步按钮点击
                syncButton.on('click', function(e) {
                    e.preventDefault();
                    const address = addressField.val();
                    if (!address) {
                        alert('请先输入代币地址');
                        return;
                    }
                    
                    syncButton.prop('disabled', true).text('同步中...');
                    
                    $.ajax({
                        url: `/admin/wallet/token/sync-metadata/${address}/`,
                        method: 'GET',
                        success: function(response) {
                            alert('同步成功！');
                            location.reload();
                        },
                        error: function(xhr) {
                            alert('同步失败：' + (xhr.responseJSON?.message || '未知错误'));
                        },
                        complete: function() {
                            syncButton.prop('disabled', false).text('同步元数据');
                        }
                    });
                });
            }
        }, 500); // 给页面一些加载时间
    });
})(django.jQuery); 