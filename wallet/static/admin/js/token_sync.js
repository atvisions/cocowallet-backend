document.addEventListener('DOMContentLoaded', function() {
    const syncBtn = document.querySelector('.sync-metadata-btn');
    const addressInput = document.querySelector('#id_address');
    const chainSelect = document.querySelector('#id_chain');
    const statusSpan = document.querySelector('.sync-status');
    
    if (syncBtn && addressInput && chainSelect) {
        syncBtn.addEventListener('click', async function() {
            const address = addressInput.value.trim();
            const chain = chainSelect.value;
            
            if (!address) {
                alert('请先输入合约地址');
                return;
            }
            
            if (!chain) {
                alert('请先选择链');
                return;
            }
            
            try {
                statusSpan.textContent = '同步中...';
                statusSpan.style.color = '#666';
                syncBtn.disabled = true;
                
                const response = await fetch(
                    `${syncBtn.dataset.url}?address=${address}&chain=${chain}`
                );
                
                const data = await response.json();
                
                if (response.ok && data.status === 'success') {
                    // 更新所有表单字段
                    const fields = {
                        'name': data.data.name,
                        'symbol': data.data.symbol,
                        'decimals': data.data.decimals,
                        'logo': data.data.logo,
                        'is_verified': data.data.is_verified,
                        'category': data.data.category,
                        'description': data.data.description,
                        'website': data.data.website,
                        'twitter': data.data.twitter,
                        'telegram': data.data.telegram,
                        'discord': data.data.discord,
                        'github': data.data.github,
                        'total_supply': data.data.total_supply,
                        'circulating_supply': data.data.circulating_supply,
                        'market_cap': data.data.market_cap,
                        'contract_type': data.data.contract_type
                    };

                    // 遍历所有字段并更新
                    for (const [field, value] of Object.entries(fields)) {
                        const input = document.querySelector(`#id_${field}`);
                        if (input) {
                            if (input.type === 'checkbox') {
                                input.checked = value;
                            } else {
                                input.value = value || '';
                            }
                        }
                    }
                    
                    statusSpan.textContent = '同步成功';
                    statusSpan.style.color = 'green';
                } else {
                    throw new Error(data.message || '同步失败');
                }
            } catch (error) {
                statusSpan.textContent = `同步失败: ${error.message}`;
                statusSpan.style.color = 'red';
            } finally {
                syncBtn.disabled = false;
            }
        });
    }
}); 