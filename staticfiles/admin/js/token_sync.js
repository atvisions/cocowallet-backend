(function($) {
    // 等待 DOM 加载完成
    $(document).ready(function() {
        // 添加同步按钮到地址字段后
        var addressField = $('#id_address');
        if (addressField.length) {
            var syncButton = $('<button/>', {
                type: 'button',
                class: 'sync-button',
                text: '同步元数据'
            });
            
            var statusSpan = $('<span/>', {
                class: 'sync-status'
            });
            
            addressField.after(statusSpan);
            addressField.after(syncButton);
            
            syncButton.on('click', function(e) {
                e.preventDefault();
                var address = addressField.val();
                
                if (!address) {
                    statusSpan.text('请先输入代币地址').css('color', 'red');
                    return;
                }
                
                var button = $(this);
                button.prop('disabled', true).text('同步中...');
                statusSpan.text('').css('color', '');
                
                var currentHost = window.location.protocol + '//' + window.location.host;
                
                $.ajax({
                    url: currentHost + '/admin/wallet/token/sync-metadata/' + address + '/',
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
                        var errorMsg = xhr.responseJSON ? xhr.responseJSON.message : '未知错误';
                        statusSpan.text('同步失败：' + errorMsg).css('color', 'red');
                    },
                    complete: function() {
                        button.prop('disabled', false).text('同步元数据');
                    }
                });
            });
        }
    });
})(window.jQuery);  // 使用 window.jQuery 而不是 django.jQuery 