// Pagination variables
let inventoryPage = 1;
let marketPage = 1;
const itemsPerPage = 5;

const ITEM_CREATE_COOLDOWN = 1 * 60;
const TOKEN_MINE_COOLDOWN = 5 * 60;

let items = [];
let pets = [];
let globalMessages = [];
let account = {};
let token = localStorage.getItem('token');
let activeChatTab = 'global';

let inventorySearchQuery = '';
let inventoryRarityFilter = '';
let inventorySaleFilter = 'all';

let marketSearchQuery = '';
let marketRarityFilter = '';
let marketPriceMin = '';
let marketPriceMax = '';
let marketSellerFilter = '';
let marketItems = [];

let unreadMessages = 0;
let isChatFocused = true;
let messageSound = new Audio('notification.mp3'); // Add sound file
let soundEnabled = true;

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
  const chatTab = document.querySelector('[data-tab="chat"]');
  if (tabName === 'chat') {
    unreadMessages = 0;
    updateNotificationBadge();
    chatTab.classList.remove('new-messages');
    isChatFocused = true;
  } else {
    isChatFocused = false;
  }

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
function handleLogin(code) {
  const username = document.getElementById('loginUsername').value;
  const password = document.getElementById('loginPassword').value;

  let body = {
    username: username,
    password: password
  }

  if (code) {
    if (code.length == 6) {
      body = {
        username: username,
        password: password,
        token: code
      }
    }
    else {
      body = {
        username: username,
        password: password,
        code: code
      }
    }
  }

  fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  })
    .then(res => res.json())
    .then(data => {
      if (data.code == "2fa-required") {
        customPrompt('Enter 2FA code or Backup code:').then(code => {
          if (!code) location.reload();
          handleLogin(code);
        });
        return;
      }

      if (data.token) {
        localStorage.setItem('token', data.token);
        token = data.token;
        showMainContent();
        refreshAccount();
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

function refreshBanner() {
  fetch('/api/get_banner', {
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => {
      if (data.banner) {
        document.getElementById('banner').style.display = 'block';
        document.getElementById('banner').innerText = data.banner.value;
      }
    });
}

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

      if (data.banned) {
        const bannedUntil = new Date(data.banned_until);
        document.getElementById('mainContent').style.display = 'none';
        document.getElementById('bannedPage').style.display = 'block';
        if (data.banned_until === 0) {
          document.getElementById('banExpires').textContent = "Permanent";
        } else {
          document.getElementById('banExpires').textContent = bannedUntil.toLocaleString();
        }
        document.getElementById('banReason').textContent = data.banned_reason;
        return;
      }

      document.getElementById('tokens').textContent = data.tokens;
      document.getElementById('level').textContent = data.level;
      document.getElementById('exp').textContent = data.exp;
      document.getElementById('usernameDisplay').textContent = data.username;
      if (data.type === 'admin') {
        document.getElementById('roleDisplay').innerHTML = `You are an <strong>Admin</strong>`;
        document.getElementById('adminDashboardTabButton').style.display = 'inline-block';
        document.getElementById('modDashboardTabButton').style.display = 'none';
        if (document.querySelector('.tab.active').getAttribute('data-tab') === 'modDashboard') {
          switchTab('dashboard');
        }
      } else if (data.type === 'mod') {
        document.getElementById('roleDisplay').innerHTML = `You are a <strong>Mod</strong>`;
        document.getElementById('modDashboardTabButton').style.display = 'inline-block';
        document.getElementById('adminDashboardTabButton').style.display = 'none';
        if (document.querySelector('.tab.active').getAttribute('data-tab') === 'adminDashboard') {
          switchTab('dashboard');
        }
      } else {
        document.getElementById('roleDisplay').innerHTML = `You are a <strong>User</strong>`;
        document.getElementById('adminDashboardTabButton').style.display = 'none';
        document.getElementById('modDashboardTabButton').style.display = 'none';
        if (document.querySelector('.tab.active').getAttribute('data-tab') === 'adminDashboard' ||
          document.querySelector('.tab.active').getAttribute('data-tab') === 'modDashboard') {
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
      applyInventoryFilters(items);

      pets = data.pets;
      renderPets(pets);

      // Update cooldowns
      const now = Date.now() / 1000;
      const remaining = ITEM_CREATE_COOLDOWN - (now - data.last_item_time);
      const cooldownEl = document.getElementById('cooldown');
      cooldownEl.innerHTML = remaining > 0 ?
        `Item creation cooldown: ${Math.ceil(remaining)}s remaining.${account.type === 'admin' ? ' <a href="#" onclick="resetCooldown()">Skip cooldown? (Admin)</a>' : ''}` : '';

      const mineRemaining = TOKEN_MINE_COOLDOWN - (now - data.last_mine_time);
      const mineCooldownEl = document.getElementById('mineCooldown');
      mineCooldownEl.innerHTML = mineRemaining > 0 ?
        `Mining cooldown: ${Math.ceil(mineRemaining)}s remaining.${account.type === 'admin' ? ' <a href="#" onclick="resetCooldown()">Skip cooldown? (Admin)</a>' : ''}` : '';
    });
}

function renderPets(pets) {
  const petsList = document.getElementById('pet-list');
  petsList.innerHTML = '';

  if (pets.length === 0) {
    const li = document.createElement('li');
    li.className = 'pet-entry';
    li.innerHTML = `
      <div class="pet-entry-content">
        <p>You have no pets.</p>
        <button class="btn btn-primary" onclick="buyPet()">Buy a pet (100 tokens)</button>
      </div>
    `;
    petsList.appendChild(li);
    return;
  }

  pets.forEach(pet => {
    const lastFed = new Date(pet.last_fed * 1000);
    const timeAgo = new Date(Date.now() - lastFed.getTime());
    const daysAgo = Math.floor(timeAgo / (1000 * 60 * 60 * 24));

    const li = document.createElement('li');
    li.className = 'pet-entry';
    li.innerHTML = `
      <div class="pet-entry-content">
        <span class="pet-info">
          <strong>${pet.name}</strong> - Level ${pet.level}<br>
          Status: <span class="pet-status pet-status-${pet.status}">${pet.status.charAt(0).toUpperCase() + pet.status.slice(1)}</span><br>
          <span class="feeding-status">Last fed: ${daysAgo === 0 ? 'today' : `${daysAgo} days ago`}</span>
          <button class="btn btn-primary" onclick="feedPet('${pet.id}')">Feed (10 tokens)</button>
        </span>
      </div>
    `;
    petsList.appendChild(li);
  });
}

function applyInventoryFilters(items) {
  const oldQuery = inventorySearchQuery;
  const oldRarity = inventoryRarityFilter;
  const oldSale = inventorySaleFilter;

  inventorySearchQuery = document.getElementById('inventorySearch').value.toLowerCase();
  inventoryRarityFilter = document.getElementById('inventoryRarityFilter').value;
  inventorySaleFilter = document.getElementById('inventorySaleFilter').value;

  if (oldQuery !== inventorySearchQuery || oldRarity !== inventoryRarityFilter || oldSale !== inventorySaleFilter) {
    inventoryPage = 1;
  }

  const filtered = items.filter(item => {
    const fullName = `${item.name.adjective} ${item.name.material} ${item.name.noun} ${item.name.suffix} #${item.name.number}`.toLowerCase();
    const matchesSearch = fullName.includes(inventorySearchQuery);
    const matchesRarity = !inventoryRarityFilter || item.level === inventoryRarityFilter;
    let matchesSale = true;
    if (inventorySaleFilter === 'forsale') {
      matchesSale = item.for_sale;
    } else if (inventorySaleFilter === 'notforsale') {
      matchesSale = !item.for_sale;
    }
    return matchesSearch && matchesRarity && matchesSale;
  });

  renderInventory(filtered);
}

function applyMarketFilters(items) {
  const oldQuery = marketSearchQuery;
  const oldRarity = marketRarityFilter;
  const oldPriceMin = marketPriceMin;
  const oldPriceMax = marketPriceMax;
  const oldSeller = marketSellerFilter;

  marketSearchQuery = document.getElementById('marketSearch').value.toLowerCase();
  marketRarityFilter = document.getElementById('marketRarityFilter').value;
  marketPriceMin = document.getElementById('marketPriceMin').value;
  marketPriceMax = document.getElementById('marketPriceMax').value;
  marketSellerFilter = document.getElementById('marketSellerFilter').value.toLowerCase();

  if (oldQuery !== marketSearchQuery || oldRarity !== marketRarityFilter || oldPriceMin !== marketPriceMin || oldPriceMax !== marketPriceMax || oldSeller !== marketSellerFilter) {
    marketPage = 1;
  }

  const filtered = items.filter(item => {
    const fullName = `${item.name.adjective} ${item.name.material} ${item.name.noun} ${item.name.suffix} #${item.name.number}`.toLowerCase();
    const matchesSearch = fullName.includes(marketSearchQuery);
    const matchesRarity = !marketRarityFilter || item.level === marketRarityFilter;
    const price = item.price;
    const min = marketPriceMin ? Number(marketPriceMin) : -Infinity;
    const max = marketPriceMax ? Number(marketPriceMax) : Infinity;
    const matchesPrice = price >= min && price <= max;
    const matchesSeller = !marketSellerFilter || item.owner.toLowerCase().includes(marketSellerFilter);
    return matchesSearch && matchesRarity && matchesPrice && matchesSeller;
  });

  renderMarketplace(filtered);
}

function refreshMarket() {
  const token = localStorage.getItem('token');
  fetch('/api/market', {
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => {
      marketItems = data;
      applyMarketFilters(data);
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
    li.className = 'item-entry';
    li.innerHTML = `
      <span class="item-info">
        ${item.name.icon} 
        ${item.name.adjective} 
        ${item.name.material} 
        ${item.name.noun} 
        ${item.name.suffix} #${item.name.number}
        <span class="item-meta">(${item.rarity} Lv.${item.level})</span>
        ${item.for_sale ? `<span class="sale-indicator">💰 Selling for ${item.price} tokens</span>` : ''}
      </span>
    `;

    // Action buttons container
    const btnContainer = document.createElement('div');
    btnContainer.className = 'item-actions';

    // Sell/Cancel Sale button
    const sellBtn = document.createElement('button');
    sellBtn.className = `btn ${item.for_sale ? 'btn-warning' : 'btn-secondary'}`;
    sellBtn.innerHTML = item.for_sale ? '🚫 Cancel' : '💰 Sell';
    sellBtn.onclick = item.for_sale
      ? () => cancelSale(item.id)
      : () => sellItem(item.id);

    // View Secret button
    const viewSecretBtn = document.createElement('button');
    viewSecretBtn.className = 'btn btn-danger';
    viewSecretBtn.innerHTML = '🕵️ Secret';
    viewSecretBtn.onclick = () => viewSecret(item.id);

    btnContainer.appendChild(sellBtn);
    btnContainer.appendChild(viewSecretBtn);

    // Admin controls
    if (account.type === 'admin') {
      const editBtn = document.createElement('button');
      editBtn.className = 'btn btn-admin';
      editBtn.innerHTML = '✏️ Edit';
      editBtn.onclick = () => editItem(item.id);

      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'btn btn-admin-danger';
      deleteBtn.innerHTML = '🗑️ Delete';
      deleteBtn.onclick = () => deleteItem(item.id);

      btnContainer.appendChild(editBtn);
      btnContainer.appendChild(deleteBtn);
    }

    li.appendChild(btnContainer);
    itemsList.appendChild(li);
  });

  // Pagination controls
  const paginationContainer = document.getElementById('inventoryPagination');
  paginationContainer.innerHTML = '';
  const totalPages = Math.ceil(inventoryItems.length / itemsPerPage);

  const prevBtn = document.createElement('button');
  prevBtn.className = 'btn btn-pagination';
  prevBtn.innerHTML = '◀ Previous';
  prevBtn.disabled = inventoryPage === 1;
  prevBtn.onclick = () => {
    if (inventoryPage > 1) {
      inventoryPage--;
      renderInventory(inventoryItems);
    }
  };

  const nextBtn = document.createElement('button');
  nextBtn.className = 'btn btn-pagination';
  nextBtn.innerHTML = 'Next ▶';
  nextBtn.disabled = inventoryPage >= totalPages;
  nextBtn.onclick = () => {
    if (inventoryPage < totalPages) {
      inventoryPage++;
      renderInventory(inventoryItems);
    }
  };

  const pageInfo = document.createElement('span');
  pageInfo.className = 'pagination-info';
  pageInfo.innerHTML = `
    Page <strong>${inventoryPage}</strong> 
    of <strong>${totalPages}</strong> 
    (${inventoryItems.length} items total)
  `;

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
    li.className = 'market-item';
    li.innerHTML = `
      <div class="item-header">
        <span class="item-icon">${item.name.icon}</span>
        <span class="item-name">
          ${item.name.adjective} 
          ${item.name.material} 
          ${item.name.noun} 
          ${item.name.suffix} #${item.name.number}
        </span>
      </div>
      <div class="item-details">
        <span class="item-level">⚔️ ${item.rarity} ${item.level}</span>
        <span class="item-price">💰 ${item.price} tokens</span>
        <span class="item-seller">👤 ${item.owner}</span>
      </div>
    `;

    if (item.owner !== account.username) {
      const buyBtn = document.createElement('button');
      buyBtn.className = 'btn btn-buy';
      buyBtn.innerHTML = '🛒 Purchase';
      buyBtn.onclick = () => buyItem(item.id);

      const btnContainer = document.createElement('div');
      btnContainer.className = 'market-actions';
      btnContainer.appendChild(buyBtn);
      li.appendChild(btnContainer);
    }

    marketList.appendChild(li);
  });

  // Pagination controls
  const paginationContainer = document.getElementById('marketplacePagination');
  paginationContainer.innerHTML = '';
  const totalPages = Math.ceil(marketItems.length / itemsPerPage);

  const prevBtn = document.createElement('button');
  prevBtn.className = 'btn btn-pagination';
  prevBtn.innerHTML = '◀ Previous';
  prevBtn.disabled = marketPage === 1;
  prevBtn.onclick = () => {
    if (marketPage > 1) {
      marketPage--;
      renderMarketplace(marketItems);
    }
  };

  const nextBtn = document.createElement('button');
  nextBtn.className = 'btn btn-pagination';
  nextBtn.innerHTML = 'Next ▶';
  nextBtn.disabled = marketPage >= totalPages;
  nextBtn.onclick = () => {
    if (marketPage < totalPages) {
      marketPage++;
      renderMarketplace(marketItems);
    }
  };

  const pageInfo = document.createElement('span');
  pageInfo.className = 'pagination-info';
  pageInfo.innerHTML = `
    Page <strong>${marketPage}</strong> 
    of <strong>${totalPages}</strong> 
    (Showing ${pagedItems.length} of ${marketItems.length} listings)
  `;

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
      customAlert(`Mined ${data.tokens} tokens!`).then(() => {
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
      customPrompt("Enter new rarity (blank for no change):").then(newRarity => {
        fetch('/api/edit_item', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
          body: JSON.stringify({ item_id: item_id, new_name: newName, new_icon: newIcon, new_rarity: newRarity })
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
        document.getElementById('messageInput').value = '';
        refreshGlobalMessages();
      } else {
        customAlert('Error sending message: ' + data.error);
      }
    });
}

function sanitizeHTML(html) {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div.textContent || div.innerText || '';
}

function deleteMessage(messageId) {
  fetch('/api/delete_message', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify({ message_id: messageId })
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        refreshGlobalMessages();
      } else {
        customAlert('Error deleting message.');
      }
    });
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
        const wasAtBottom = isUserAtBottom(globalMessagesContainer);

        console.debug(globalMessages);

        if (data.messages.length === globalMessages.length) {
          console.log('No new messages');
          return;
        }

        // Clear existing messages
        globalMessagesContainer.innerHTML = '';

        // Append new messages to DOM and trim old ones
        data.messages.forEach(message => {
          handleNewMessage(message);
        });

        if (wasAtBottom) {
          scrollToBottom(globalMessagesContainer);
        }

        globalMessages = data.messages;
      }
    });
}

// Enhanced message display
function appendMessage(message) {
  const messagesContainer = document.getElementById('globalMessages');
  const isOwnMessage = message.username === account.username;
  const messageType = message.type || 'user';

  const messageEl = document.createElement('div');
  messageEl.className = `message ${messageType} ${isOwnMessage ? 'own-message' : ''}`;
  messageEl.innerHTML = `
    <div class="message-header">
      <span class="message-sender ${messageType}" title="${messageType.charAt(0).toUpperCase() + messageType.slice(1)}">
        ${messageType === 'system' ? '⚙️' : ''}
        ${messageType === 'admin' ? '🛠️' : ''}
        ${messageType === 'mod' ? '🛡️' : ''}
        ${message.username}
      </span>
      <span class="message-time">${formatTime(message.timestamp)}</span>
    </div>
    <div class="message-content">${sanitizeHTML(message.message)}</div>
    ${account.type === 'admin' || account.type === 'mod' ?
      `<button class="delete-message" onclick="deleteMessage('${message.id}')">🗑️</button>` : ''}
  `;

  messagesContainer.appendChild(messageEl);

  // Trim old messages from DOM to keep max 200
  const MAX_DOM_MESSAGES = 200;
  const messageElements = messagesContainer.getElementsByClassName('message');
  while (messageElements.length > MAX_DOM_MESSAGES) {
    messagesContainer.removeChild(messageElements[0]);
  }

  // Auto-scroll if at bottom
  if (isUserAtBottom(messagesContainer)) {
    scrollToBottom(messagesContainer);
  }
}

// New time formatter
function formatTime(timestamp) {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}


function handleNewMessage(message) {
  const activeTab = document.querySelector('.tab.active').dataset.tab;

  if (activeTab !== 'chat') {
    unreadMessages++;
    updateNotificationBadge();
    if (soundEnabled) messageSound.play();
  }

  if (!isChatFocused) {
    document.querySelector('.chat-tab-button').classList.add('new-messages');
  }

  appendMessage(message);
}

// New notification badge
function updateNotificationBadge() {
  const badge = document.getElementById('chatNotificationBadge');
  badge.textContent = unreadMessages;
  badge.style.display = unreadMessages > 0 ? 'block' : 'none';
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
    customPrompt("Enter reason for banning:").then(reason => {
      if (!reason) return;
      customPrompt("Enter length of ban (e.g. 1s, 1m, 1h, 1d, 1w, 1m, 1y, 1y+6m, perma):").then(length => {
        if (!length) return;
        fetch('/api/ban_user', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
          body: JSON.stringify({ username: username, reason: reason, length: length })
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
    });
  });
}

function unbanUser() {
  customPrompt("Enter username to unban:").then(username => {
    if (!username) return;
    fetch('/api/unban_user', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ username: username })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('User unbanned!').then(() => {
            refreshAccount();
          });
        } else {
          customAlert('Error unbanning user.');
        }
      });
  });
}
function muteUser() {
  customPrompt("Enter username to mute:").then(username => {
    if (!username) return;
    customPrompt("Enter length of mute (e.g. 1s, 1m, 1h, 1d, 1w, 1m, 1y, 1y+6m, perma):").then(length => {
      if (!length) return;
      fetch('/api/mute_user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ username: username, length: length })
      })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            customAlert('User muted!').then(() => {
              refreshAccount();
            });
          } else {
            customAlert('Error muting user.');
          }
        });
    });
  });
}

function unmuteUser() {
  customPrompt("Enter username to unmute:").then(username => {
    if (!username) return;
    fetch('/api/unmute_user', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ username: username })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('User unmuted!').then(() => {
            refreshAccount();
          });
        } else {
          customAlert('Error unmuting user.');
        }
      });
  });
}

function fineUser() {
  customPrompt("Enter username to fine:").then(username => {
    if (!username) return;
    customPrompt("Enter amount of fine:").then(amount => {
      if (!amount) return;
      fetch('/api/fine_user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ username: username, amount: parseFloat(amount) })
      })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            customAlert('User fined!').then(() => {
              refreshAccount();
            });
          } else {
            customAlert('Error fining user.');
          }
        });
    });
  });
}

function setBanner() {
  customPrompt("Enter banner:").then(banner => {
    if (!banner) return;
    fetch('/api/set_banner', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ banner: banner })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('Banner set!').then(() => {
            refreshBanner();
          });
        } else {
          customAlert('Error setting banner.');
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
        let container = document.createElement("DIV");
        for (let user in data.usernames){
            let username = data.usernames[user];

            let p = document.createElement("P");
            p.innerText = username;
            p.appendChild(document.createElement("BR"))

            container.appendChild(p)
        }
        customAlert(container.innerHTML);
      }
    });
};

function editExp() {
  customPrompt("Enter exp:").then(exp => {
    if (!exp) return;
    fetch('/api/edit_exp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ exp: parseFloat(exp) })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('Exp edited!').then(() => {
            refreshAccount();
          });
        } else {
          customAlert('Error editing exp.');
        }
      });
  });
}

function editExpForUser() {
  customPrompt("Enter username:").then(username => {
    if (!username) return;
    customPrompt("Enter exp:").then(exp => {
      if (!exp) return;
      fetch('/api/edit_exp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ exp: parseFloat(exp), username: username })
      })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            customAlert('Exp edited!').then(() => {
              refreshAccount();
            });
          } else {
            customAlert('Error editing exp.');
          }
        });
    });
  });
}

function editLevel() {
  customPrompt("Enter level:").then(level => {
    if (!level) return;
    fetch('/api/edit_level', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ level: parseFloat(level) })
    })
      .then(res => res.json())
      .then(data => {
        if (data.success) {
          customAlert('Level edited!').then(() => {
            refreshAccount();
          });
        } else {
          customAlert('Error editing level.');
        }
      });
  });
}

function editLevelForUser() {
  customPrompt("Enter username:").then(username => {
    if (!username) return;
    customPrompt("Enter level:").then(level => {
      if (!level) return;
      fetch('/api/edit_level', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ level: parseFloat(level), username: username })
      })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            customAlert('Level edited!').then(() => {
              refreshAccount();
            });
          } else {
            customAlert('Error editing level.');
          }
        });
    });
  });
}

function deleteAccount() {
  customPrompt("Enter 'CONFIRM' to confirm you want to delete your account:").then(input => {
    if (input === 'CONFIRM') {
      fetch('/api/delete_account', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      })
        .then(res => res.json())
        .then(data => {
          if (data.success) {
            localStorage.removeItem('token');
            location.reload();
          }
          else {
            customAlert("Failed to delete account.");
          }
        })
    }
  });
}

let backupCode = '';

function setup2FA() {
  // Generate QR code
  fetch('/api/setup_2fa', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        backupCode = data.backup_code;
        fetch('/api/2fa_qrcode', {
          method: 'GET',
          headers: { 'Authorization': `Bearer ${token}` }
        })
          .then(res => res.blob())
          .then(blob => {
            const url = URL.createObjectURL(blob);
            const qrCodeImage = document.getElementById('2faQrCode');
            qrCodeImage.src = url;
            qrCodeImage.style.display = 'block';

            // Hide main content
            document.getElementById('mainContent').style.display = 'none';

            // Show 2FA setup page
            document.getElementById('2faSetupPage').style.display = 'block';
          });
      }
      else {
        customAlert(`Error setting up 2FA: ${data.error}`);
        return;
      }
    });
}

function enable2FA() {
  const code = document.getElementById('2faCode').value;
  fetch('/api/verify_2fa', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify({ token: code })
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        customAlert('2FA enabled! Make sure to save this backup code in a safe place: ' + backupCode).then(() => {
          location.reload();
        });
      }
      else {
        customAlert("Failed to enable 2FA.");
      }
    });
}

function disable2FA() {
  fetch('/api/disable_2fa', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        customAlert('2FA disabled!').then(() => {
          location.reload();
        });
      }
      else {
        customAlert("Failed to disable 2FA.");
      }
    });
}

function buyPet() {
  fetch('/api/buy_pet', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}` }
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        customAlert('Pet bought!').then(() => {
          refreshAccount();
        });
      }
      else {
        customAlert("Failed to buy pet.");
      }
    });
}

function feedPet(petId) {
  fetch(`/api/feed_pet`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ pet_id: petId })
  })
    .then(res => res.json())
    .then(data => {
      if (data.success) {
        customAlert('Pet fed!').then(() => {
          refreshAccount();
        });
      }
      else {
        customAlert("Failed to feed pet.");
      }
    });
}

function toggleDarkMode() {
  const currentTheme = localStorage.getItem('theme') || 'light';
  const newTheme = currentTheme === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', newTheme);
  localStorage.setItem('theme', newTheme);
}

function initializeTheme() {
  const savedTheme = localStorage.getItem('theme') || 'light';
  document.documentElement.setAttribute('data-theme', savedTheme);
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
document.getElementById('messageInput').addEventListener("keyup", function (event) {
  if (event.key === "Enter") {
    sendGlobalMessage();
  };
});
document.getElementById('toggleDarkMode').addEventListener('click', toggleDarkMode);
document.getElementById('deleteAccount').addEventListener('click', deleteAccount);
document.getElementById('logout').addEventListener('click', () => {
  localStorage.removeItem('token');
  location.reload();
});
document.getElementById('setup2FA').addEventListener('click', setup2FA);
document.getElementById('disable2FA').addEventListener('click', disable2FA);
document.getElementById('2faSetupSubmit').addEventListener('click', enable2FA);
document.getElementById('2faSetupCancel').addEventListener('click', () => {
  location.reload();
});

// Interval
setInterval(() => {
  if (!token) return;
  getStats();
  refreshBanner();
  refreshAccount();
  refreshGlobalMessages();
  refreshLeaderboard();
  refreshMarket();
}, 1000);

// Admin Dashboard event listeners
document.getElementById('listUsersAdmin').addEventListener('click', listUsers);
document.getElementById('setBannerAdmin').addEventListener('click', setBanner);
document.getElementById('editTokensAdmin').addEventListener('click', editTokens);
document.getElementById('editExpAdmin').addEventListener('click', editExp);
document.getElementById('editLevelAdmin').addEventListener('click', editLevel);
document.getElementById('editExpForUserAdmin').addEventListener('click', editExpForUser);
document.getElementById('editLevelForUserAdmin').addEventListener('click', editLevelForUser);
document.getElementById('addAdminAdmin').addEventListener('click', addAdmin);
document.getElementById('addModAdmin').addEventListener('click', addMod);
document.getElementById('removeModAdmin').addEventListener('click', removeMod);
document.getElementById('editTokensForUserAdmin').addEventListener('click', editTokensForUser);
document.getElementById('banUserAdmin').addEventListener('click', banUser);
document.getElementById('unbanUserAdmin').addEventListener('click', unbanUser);
document.getElementById('muteUserAdmin').addEventListener('click', muteUser);
document.getElementById('unmuteUserAdmin').addEventListener('click', unmuteUser);
document.getElementById('fineUserAdmin').addEventListener('click', fineUser);

// Mod Dashboard event listeners
document.getElementById('listUsersMod').addEventListener('click', listUsers);
document.getElementById('muteUserMod').addEventListener('click', muteUser);
document.getElementById('unmuteUserMod').addEventListener('click', unmuteUser);

// Initial data refresh
initializeTheme();
getStats();

if (token) {
  showMainContent();
  refreshAccount();
}