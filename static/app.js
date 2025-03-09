let items = [];
let account = {};
let token = null;
// Pagination variables
let inventoryPage = 1;
let marketPage = 1;
const itemsPerPage = 5;

const ITEM_CREATE_COOLDOWN = 60;
const TOKEN_MINE_COOLDOWN = 600;

let activeChatTab = 'global';

// Custom modal functions
function customAlert(message) {
  console.log(message);
  return new Promise((resolve) => {
    const modal = document.getElementById('customModal');
    const modalMessage = document.getElementById('modalMessage');
    const modalInputContainer = document.getElementById('modalInputContainer');
    modalMessage.innerHTML = message;
    modalInputContainer.style.display = "none";
    modal.style.display = "block";

    const okBtn = document.getElementById('modalOk');
    const cancelBtn = document.getElementById('modalCancel');
    const modalClose = document.getElementById('modalClose');

    cancelBtn.style.display = "none";

    okBtn.onclick = () => {
      modal.style.display = "none";
      resolve();
    };
    modalClose.onclick = () => {
      modal.style.display = "none";
      resolve();
    };
  });
}

function customPrompt(message) {
  return new Promise((resolve) => {
    const modal = document.getElementById('customModal');
    const modalMessage = document.getElementById('modalMessage');
    const modalInputContainer = document.getElementById('modalInputContainer');
    const modalInput = document.getElementById('modalInput');
    modalMessage.textContent = message;
    modalInputContainer.style.display = "block";
    modal.style.display = "block";
    modalInput.value = "";

    const okBtn = document.getElementById('modalOk');
    const cancelBtn = document.getElementById('modalCancel');
    const modalClose = document.getElementById('modalClose');

    cancelBtn.style.display = "inline-block";

    okBtn.onclick = () => {
      modal.style.display = "none";
      resolve(modalInput.value);
    };
    cancelBtn.onclick = () => {
      modal.style.display = "none";
      resolve(null);
    };
    modalClose.onclick = () => {
      modal.style.display = "none";
      resolve(null);
    };
  });
}

function customConfirm(message) {
  return new Promise((resolve) => {
    const modal = document.getElementById('customModal');
    const modalMessage = document.getElementById('modalMessage');
    const modalInputContainer = document.getElementById('modalInputContainer');
    modalMessage.textContent = message;
    modalInputContainer.style.display = "none";
    modal.style.display = "block";

    const okBtn = document.getElementById('modalOk');
    const cancelBtn = document.getElementById('modalCancel');
    const modalClose = document.getElementById('modalClose');

    okBtn.style.display = "inline-block";
    cancelBtn.style.display = "inline-block";

    okBtn.onclick = () => {
      modal.style.display = "none";
      resolve(true);
    };
    cancelBtn.onclick = () => {
      modal.style.display = "none";
      resolve(false);
    };
    modalClose.onclick = () => {
      modal.style.display = "none";
      resolve(false);
    };
  });
}

// Tab Switching Logic
function switchTab(tabName) {
  // Remove active class from all tabs and hide all content
  document.querySelectorAll('.tab').forEach(btn => {
    btn.classList.remove('active');
  });
  document.querySelectorAll('.tab-content').forEach(content => {
    content.classList.remove('active');
  });

  // Activate the clicked tab and its content
  document.querySelector(`.tab[data-tab="${tabName}"]`).classList.add('active');
  document.getElementById('tab-' + tabName).classList.add('active');
}

// Set up event listeners for tab buttons
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    switchTab(btn.getAttribute('data-tab'));
  });
});

// Auth functions
function handleLogin() {
  const username = document.getElementById('loginUsername').value;
  const password = document.getElementById('loginPassword').value;

  fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  })
    .then(res => res.json())
    .then(data => {
      if (data.token) {
        localStorage.setItem('token', data.token);
        token = data.token;
        showMainContent();
        refreshAccount();
      } else {
        customAlert('Login failed: ' + (data.error || 'Unknown error'));
      }
    });
}

function handleRegister() {
  const username = document.getElementById('registerUsername').value;
  const password = document.getElementById('registerPassword').value;

  fetch('/api/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        customAlert('Registration successful! Please login.');
      } else {
        customAlert('Registration failed: ' + (data.error || 'Unknown error'));
      }
    });
}

function showMainContent() {
  document.getElementById('authForms').style.display = 'none';
  document.getElementById('mainContent').style.display = 'block';
}

// Modified API functions with auth headers
function refreshAccount() {
  const token = localStorage.getItem('token');
  fetch('/api/account', {
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => {
      if (data.error) {
        localStorage.removeItem('token');
        location.reload();
        return;
      }

      document.getElementById('tokens').textContent = data.tokens;
      document.getElementById('usernameDisplay').textContent = data.username;
      if (data.type === 'admin') {
        document.getElementById('roleDisplay').innerHTML = `You are an <strong>Admin</strong>`;
        // Show admin tab button if admin
        document.getElementById('adminDashboardTabButton').style.display = 'inline-block';
      } else if (data.type === 'mod') {
        document.getElementById('roleDisplay').innerHTML = `You are a <strong>Mod</strong>`;
        document.getElementById('adminDashboardTabButton').style.display = 'none';
        // If currently in the admin dashboard, switch back to Dashboard
        if (document.querySelector('.tab.active').getAttribute('data-tab') === 'adminDashboard') {
          switchTab('dashboard');
        }
      } else {
        document.getElementById('roleDisplay').innerHTML = `You are a <strong>User</strong>`;
        document.getElementById('adminDashboardTabButton').style.display = 'none';
        // If currently in the admin dashboard, switch back to Dashboard
        if (document.querySelector('.tab.active').getAttribute('data-tab') === 'adminDashboard') {
          switchTab('dashboard');
        }
      }
      items = data.items;
      account = data;

      // Reset inventory page if items length changes significantly
      if ((inventoryPage - 1) * itemsPerPage >= items.length) {
        inventoryPage = 1;
      }
      // Render inventory with pagination
      renderInventory(items);

      // Update cooldowns
      const now = Date.now() / 1000;
      const remaining = ITEM_CREATE_COOLDOWN - (now - data.last_item_time);
      const cooldownEl = document.getElementById('cooldown');
      cooldownEl.innerHTML = remaining > 0 ?
        `Item creation cooldown: ${Math.ceil(remaining)}s remaining.${account.type === 'admin' ? ' <a href="#" onclick="resetCooldown()">Skip cooldown? (Admin)</a>' : ''}` : '';

      const mineRemaining = TOKEN_MINE_COOLDOWN - (now - data.last_mine_time);
      const mineCooldownEl = document.getElementById('mineCooldown');
      mineCooldownEl.innerHTML = mineRemaining > 0 ?
        `Mining cooldown: ${Math.ceil(mineRemaining / 60)}m remaining.${account.type === 'admin' ? ' <a href="#" onclick="resetCooldown()">Skip cooldown? (Admin)</a>' : ''}` : '';
    });
}

function refreshMarket() {
  const token = localStorage.getItem('token');
  fetch('/api/market', {
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => {
      if ((marketPage - 1) * itemsPerPage >= data.length) {
        marketPage = 1;
      }
      renderMarketplace(data);
    });
}

// Render inventory items with pagination
function renderInventory(inventoryItems) {
  const itemsList = document.getElementById('itemsList');
  itemsList.innerHTML = '';

  const startIndex = (inventoryPage - 1) * itemsPerPage;
  const pagedItems = inventoryItems.slice(startIndex, startIndex + itemsPerPage);

  pagedItems.forEach(item => {
    const li = document.createElement('li');
    li.textContent = `${item.name.icon} ${item.name.adjective} ${item.name.material} ${item.name.noun} ${item.name.suffix} #${item.name.number} ${item.for_sale ? "(For Sale)" : ""}`;

    const sellBtn = document.createElement('button');
    sellBtn.classList.add('btn', 'btn-secondary');
    sellBtn.textContent = item.for_sale ? 'Cancel Sale' : 'Sell';
    sellBtn.onclick = item.for_sale ? () => cancelSale(item.id) : () => sellItem(item.id);

    const viewSecretBtn = document.createElement('button');
    viewSecretBtn.classList.add('btn', 'btn-danger');
    viewSecretBtn.textContent = 'View Secret';
    viewSecretBtn.onclick = () => viewSecret(item.id);

    li.appendChild(sellBtn);
    li.appendChild(viewSecretBtn);

    if (account.type === 'admin') {
      const editBtn = document.createElement('button');
      editBtn.classList.add('btn', 'btn-primary');
      editBtn.textContent = 'Edit (Admin)';
      editBtn.onclick = () => editItem(item.id);

      const deleteBtn = document.createElement('button');
      deleteBtn.classList.add('btn', 'btn-danger');
      deleteBtn.textContent = 'Delete (Admin)';
      deleteBtn.onclick = () => deleteItem(item.id);

      li.appendChild(editBtn);
      li.appendChild(deleteBtn);
    }

    itemsList.appendChild(li);
  });

  // Update pagination controls for inventory
  const paginationContainer = document.getElementById('inventoryPagination');
  paginationContainer.innerHTML = '';
  const totalPages = Math.ceil(inventoryItems.length / itemsPerPage);

  const prevBtn = document.createElement('button');
  prevBtn.textContent = 'Prev';
  prevBtn.classList.add('btn', 'btn-primary');
  prevBtn.disabled = inventoryPage === 1;
  prevBtn.onclick = () => {
    if (inventoryPage > 1) {
      inventoryPage--;
      renderInventory(inventoryItems);
    }
  };

  const nextBtn = document.createElement('button');
  nextBtn.textContent = 'Next';
  nextBtn.classList.add('btn', 'btn-primary');
  nextBtn.disabled = inventoryPage >= totalPages;
  nextBtn.onclick = () => {
    if (inventoryPage < totalPages) {
      inventoryPage++;
      renderInventory(inventoryItems);
    }
  };

  const pageInfo = document.createElement('span');
  pageInfo.textContent = ` Page ${inventoryPage} of ${totalPages} `;

  paginationContainer.appendChild(prevBtn);
  paginationContainer.appendChild(pageInfo);
  paginationContainer.appendChild(nextBtn);
}

// Render marketplace items with pagination
function renderMarketplace(marketItems) {
  const marketList = document.getElementById('marketList');
  marketList.innerHTML = '';

  const startIndex = (marketPage - 1) * itemsPerPage;
  const pagedItems = marketItems.slice(startIndex, startIndex + itemsPerPage);

  pagedItems.forEach(item => {
    const li = document.createElement('li');
    li.textContent = `${item.name.icon} ${item.name.adjective} ${item.name.material} ${item.name.noun} ${item.name.suffix} #${item.name.number} - Price: ${item.price} tokens - Sold by: ${item.owner}`;
    if (item.owner !== account.username) {
      const buyBtn = document.createElement('button');
      buyBtn.classList.add('btn', 'btn-primary');
      buyBtn.textContent = 'Buy';
      buyBtn.onclick = () => buyItem(item.id);
      li.appendChild(buyBtn);
    }
    marketList.appendChild(li);
  });

  // Update pagination controls for marketplace
  const paginationContainer = document.getElementById('marketplacePagination');
  paginationContainer.innerHTML = '';
  const totalPages = Math.ceil(marketItems.length / itemsPerPage);

  const prevBtn = document.createElement('button');
  prevBtn.textContent = 'Prev';
  prevBtn.classList.add('btn', 'btn-primary');
  prevBtn.disabled = marketPage === 1;
  prevBtn.onclick = () => {
    if (marketPage > 1) {
      marketPage--;
      renderMarketplace(marketItems);
    }
  };

  const nextBtn = document.createElement('button');
  nextBtn.textContent = 'Next';
  nextBtn.classList.add('btn', 'btn-primary');
  nextBtn.disabled = marketPage >= totalPages;
  nextBtn.onclick = () => {
    if (marketPage < totalPages) {
      marketPage++;
      renderMarketplace(marketItems);
    }
  };

  const pageInfo = document.createElement('span');
  pageInfo.textContent = ` Page ${marketPage} of ${totalPages} `;

  paginationContainer.appendChild(prevBtn);
  paginationContainer.appendChild(pageInfo);
  paginationContainer.appendChild(nextBtn);
}

// API call examples
function createItem() {
  const token = localStorage.getItem('token');
  fetch('/api/create_item', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(item => {
      if (item.error) {
        customAlert(`Error creating item: ${item.error}`);
        return;
      }
      customAlert(`Created item: ${item.name.icon} ${item.name.adjective} ${item.name.material} ${item.name.noun} ${item.name.suffix} #${item.name.number}`).then(() => {
        refreshAccount();
      });
    });
}

function buyItem(itemId) {
  const token = localStorage.getItem('token');
  fetch('/api/buy_item', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body: JSON.stringify({ item_id: itemId })
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        customAlert('Item purchased!').then(() => {
          refreshAccount();
          refreshMarket();
        });
      }
    });
}

function viewSecret(itemId) {
  let item = items.find(item => item.id == itemId);
  customAlert(`Secret (do not share - it will let people take your item): ${item.item_secret}`);
}

function mineTokens() {
  fetch('/api/mine_tokens', { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } })
    .then(res => res.json())
    .then(data => {
      if (data.error) {
        customAlert(`Error mining tokens: ${data.error}`);
        return;
      }
      customAlert(`Mined tokens! You now have ${data.tokens} tokens.`).then(() => {
        refreshAccount();
      });
    });
}

function sellItem(itemId) {
  customPrompt("Enter sale price (tokens):").then(price => {
    if (!price) return;
    fetch('/api/sell_item', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ item_id: itemId, price: parseInt(price) })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('Item listed for sale!').then(() => {
            refreshAccount();
            refreshMarket();
          });
        } else {
          customAlert('Error listing item.');
        }
      });
  });
}

function cancelSale(itemId) {
  fetch('/api/sell_item', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify({ item_id: itemId, price: 1 })
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        customAlert('Sale cancelled!').then(() => {
          refreshAccount();
          refreshMarket();
        });
      } else {
        customAlert('Error cancelling sale.');
      }
    });
}

function takeItem() {
  customPrompt("Enter secret:").then(secret => {
    if (!secret) return;
    fetch('/api/take_item', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ item_secret: secret })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('Item taken!').then(() => {
            refreshAccount();
            refreshMarket();
          });
        } else {
          customAlert('Error taking item.');
        }
      });
  });
}

function resetCooldown() {
  fetch('/api/reset_cooldowns', { method: 'POST', headers: { 'Authorization': `Bearer ${token}` } })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        customAlert('Cooldown reset!').then(() => {
          refreshAccount();
        });
      } else {
        customAlert('Error resetting cooldown.');
      }
    });
}

// Admin Functions (used in the Admin Dashboard tab)
function editTokens() {
  customPrompt("Enter tokens:").then(tokens => {
    if (!tokens) return;
    fetch('/api/edit_tokens', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ tokens: parseInt(tokens) })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('Tokens edited!').then(() => {
            refreshAccount();
          });
        } else {
          customAlert('Error editing tokens.');
        }
      });
  });
}

function editTokensForUser() {
  customPrompt("Enter username:").then(username => {
    customPrompt("Enter tokens:").then(tokens => {
      if (!tokens) return;
      fetch('/api/edit_tokens', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ tokens: parseFloat(tokens), username: username })
      })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            customAlert('Tokens edited!').then(() => {
              refreshAccount();
            });
          } else {
            customAlert('Error editing tokens.');
          }
        });
    });
  });
}

function addAdmin() {
  customPrompt("Enter username:").then(username => {
    if (!username) return;
    fetch('/api/add_admin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ username: username })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('Admin added!').then(() => {
            refreshAccount();
          });
        } else {
          customAlert('Error adding admin.');
        }
      });
  });
}

function addMod() {
  customPrompt("Enter username:").then(username => {
    if (!username) return;
    fetch('/api/add_mod', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ username: username })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('Mod added!').then(() => {
            refreshAccount();
          });
        } else {
          customAlert('Error adding mod.');
        }
      });
  });
}

function removeMod() {
  customPrompt("Enter username:").then(username => {
    if (!username) return;
    fetch('/api/remove_mod', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ username: username })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('Mod removed!').then(() => {
            refreshAccount();
          });
        } else {
          customAlert('Error removing mod.');
        }
      });
  });
}

function editItem(item_id) {
  customPrompt("Enter new name (blank for no change):").then(newName => {
    customPrompt("Enter new icon (blank for no change):").then(newIcon => {
      fetch('/api/edit_item', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ item_id: item_id, new_name: newName, new_icon: newIcon })
      })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            customAlert('Item edited!').then(() => {
              refreshAccount();
            });
          } else {
            customAlert('Error editing item.');
          }
        });
    });
  });
}

function deleteItem(item_id) {
  if (customConfirm("Are you sure you want to delete this item?")) {
    fetch('/api/delete_item', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ item_id: item_id })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('Item deleted!').then(() => {
            refreshAccount();
          });
        } else {
          customAlert('Error deleting item.');
        }
      });
  }
}

// Global chat
function sendGlobalMessage() {
  const message = document.getElementById('messageInput').value;
  if (!message) return;
  fetch('/api/send_message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify({ room: 'global', message: message })
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        refreshMessages();
      } else {
        customAlert('Error sending message.');
      }
    });
  scrollToBottom(document.getElementById('globalMessages'));
}

function sanitizeHTML(html) {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div.textContent || div.innerText || '';
}

function refreshGlobalMessages() {
  fetch('/api/get_messages?room=global', {
    method: 'GET',
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => {
      if (data.messages) {
        const globalMessagesContainer = document.getElementById('globalMessages');
        // Check if the user is at the bottom before updating the messages.
        const wasAtBottom = isUserAtBottom(globalMessagesContainer);

        // Clear the current messages.
        globalMessagesContainer.innerHTML = '';
        data.messages.forEach(message => {
          const messageElement = document.createElement('div');
          messageElement.classList.add('message');
          messageElement.innerHTML = `<b>${sanitizeHTML(message.username)}:</b> ${sanitizeHTML(message.message)}`;
          globalMessagesContainer.appendChild(messageElement);
        });

        // Auto-scroll only if the user was already at the bottom.
        if (wasAtBottom) {
          scrollToBottom(globalMessagesContainer);
        }
      }
    });
}

function refreshLeaderboard() {
  fetch('/api/leaderboard', {
    method: 'GET',
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => {
      if (data.leaderboard) {
        document.getElementById('leaderboard').innerHTML = '';
        data.leaderboard.forEach(user => {
          const leaderboardElement = document.createElement('div');
          if (user.username === account.username) {
            leaderboardElement.classList.add('highlight');
          }
          leaderboardElement.innerHTML = `<b>${user.place}:</b> ${user.username} (${user.tokens} tokens)`;
          document.getElementById('leaderboard').appendChild(leaderboardElement);
        });
      }
    });
}

function getStats() {
  fetch('/api/stats', {
    method: 'GET',
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => {
      if (data.stats) {
        document.getElementById('stats').innerHTML = '';
        data.stats.forEach(stat => {
          const statElement = document.createElement('div');
          statElement.innerHTML = `<b>${stat.name}:</b> ${stat.value}`;
          document.getElementById('stats').appendChild(statElement);
        });
      }
    });
}

function banUser() {
  customPrompt("Enter username to ban:").then(username => {
    if (!username) return;
    fetch('/api/ban_user', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ username: username })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('User banned!').then(() => {
            refreshAccount();
          });
        } else {
          customAlert('Error banning user.');
        }
      });
  });
}

function listUsers() {
  fetch('/api/users', {
    method: 'GET',
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => {
      if (data.usernames) {
        customAlert(data.users.join('<b>;;;</b>'));
      }
    });
}

// Helper functions for auto-scrolling
function isUserAtBottom(container) {
  // Allow a small threshold (e.g., 2 pixels) for precision issues.
  return container.scrollHeight - container.scrollTop <= container.clientHeight + 2;
}

function scrollToBottom(container) {
  container.scrollTop = container.scrollHeight;
}

// Event listeners
document.getElementById('createItem').addEventListener('click', createItem);
document.getElementById('mineItem').addEventListener('click', mineTokens);
document.getElementById('takeItem').addEventListener('click', takeItem);
document.getElementById('sendMessage').addEventListener('click', sendGlobalMessage);
document.getElementById('logout').addEventListener('click', () => {
  localStorage.removeItem('token');
});

// Admin Dashboard event listeners (for the new admin tab)
document.getElementById('listUsersAdmin').addEventListener('click', listUsers);
document.getElementById('editTokensAdmin').addEventListener('click', editTokens);
document.getElementById('addAdminAdmin').addEventListener('click', addAdmin);
document.getElementById('addModAdmin').addEventListener('click', addMod);
document.getElementById('removeModAdmin').addEventListener('click', removeMod);
document.getElementById('editTokensForUserAdmin').addEventListener('click', editTokensForUser);
document.getElementById('banUserAdmin').addEventListener('click', banUser);

// Interval to refresh account and market data
setInterval(() => {
  if (account.username) {
    refreshAccount();

    if (document.querySelector('.tab.active').getAttribute('data-tab') === 'market') {
      refreshMarket();
    }

    if (document.querySelector('.tab.active').getAttribute('data-tab') === 'chat') {
      refreshGlobalMessages();
    }

    if (document.querySelector('.tab.active').getAttribute('data-tab') === 'leaderboard') {
      refreshLeaderboard();
    }
  }
}, 1000);

// Initial data refresh
getStats();