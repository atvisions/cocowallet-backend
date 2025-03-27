(function($) {
    $(document).ready(function() {
        // 添加同步按钮到地址字段后
        const addressField = $('#id_address');
        if (addressField.length) {
            const syncButton = $('<button/>', {
                type: 'button',
                class: 'sync-button',
                text: '同步元数据'
            });
            
            // 添加状态提示元素
            const statusSpan = $('<span/>', {
                class: 'sync-status'
            });
            
            // 确保按钮和状态提示被正确插入
            addressField.after(statusSpan);
            addressField.after(syncButton);
            
            // 处理同步按钮点击
            syncButton.on('click', function(e) {
                e.preventDefault();
                const address = addressField.val();
                
                if (!address) {
                    statusSpan.text('请先输入代币地址').css('color', 'red');
                    return;
                }
                
                syncButton.prop('disabled', true).text('同步中...');
                statusSpan.text('').css('color', '');
                
                const currentHost = window.location.protocol + '//' + window.location.host;
                
                $.ajax({
                    url: `${currentHost}/admin/wallet/token/sync-metadata/${address}/`,
                    method: 'GET',
                    success: function(response) {
                        if (response.data) {
                            $('#id_name').val(response.data.name);
                            $('#id_symbol').val(response.data.symbol);
                            $('#id_decimals').val(response.data.decimals);
                            $('#id_logo').val(response.data.logo);
                            $('#id_website').val(response.data.website);
                            $('#id_twitter').val(response.data.twitter);
                            $('#id_telegram').val(response.data.telegram);
                            $('#id_discord').val(response.data.discord);
                            $('#id_description').val(response.data.description);
                            
                            statusSpan.text('同步成功').css('color', 'green');
                        } else {
                            statusSpan.text('同步成功，但未返回数据').css('color', 'orange');
                        }
                    },
                    error: function(xhr) {
                        statusSpan.text('同步失败：' + (xhr.responseJSON?.message || '未知错误')).css('color', 'red');
                    },
                    complete: function() {
                        syncButton.prop('disabled', false).text('同步元数据');
                    }
                });
            });
        }
    });
})(django.jQuery); 