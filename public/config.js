
// config.js - Configurações globais
const API_BASE_URL = window.location.origin.includes('localhost') 
    ? 'http://localhost:5000' 
    : '/api';

// Função para mostrar mensagens
function mostrarMensagem(tipo, texto) {
    const mensagemDiv = document.createElement('div');
    mensagemDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 20px;
        border-radius: 8px;
        color: white;
        font-weight: bold;
        z-index: 1000;
        animation: slideIn 0.3s ease;
    `;
    
    if (tipo === 'sucesso') {
        mensagemDiv.style.background = '#10b981';
    } else if (tipo === 'erro') {
        mensagemDiv.style.background = '#ef4444';
    } else if (tipo === 'aviso') {
        mensagemDiv.style.background = '#f59e0b';
    } else {
        mensagemDiv.style.background = '#3b82f6';
    }
    
    mensagemDiv.innerHTML = `
        ${texto}
        <button onclick="this.parentElement.remove()" 
                style="margin-left: 15px; background: none; border: none; color: white; cursor: pointer;">
            ✕
        </button>
    `;
    
    document.body.appendChild(mensagemDiv);
    
    // Auto-remover após 5 segundos
    setTimeout(() => {
        if (mensagemDiv.parentElement) {
            mensagemDiv.remove();
        }
    }, 5000);
}

// Função para verificar autenticação
async function verificarAutenticacao() {
    try {
        const response = await fetch(API_BASE_URL + '/auth/check', {
            method: 'GET',
            credentials: 'include'
        });
        
        if (!response.ok) {
            if (response.status === 401) {
                window.location.href = '/index.html?session_expired=true';
            }
            return null;
        }
        
        const data = await response.json();
        
        if (!data.authenticated) {
            window.location.href = '/index.html?session_expired=true';
            return null;
        }
        
        return data.user;
        
    } catch (error) {
        console.error('Erro de autenticação:', error);
        window.location.href = '/index.html?session_expired=true';
        return null;
    }
}

// Função para fazer logout
async function fazerLogout() {
    try {
        const response = await fetch(API_BASE_URL + '/auth/logout', {
            method: 'POST',
            credentials: 'include'
        });
        
        const data = await response.json();
        
        if (data.success) {
            mostrarMensagem('sucesso', 'Logout realizado com sucesso!');
            setTimeout(() => {
                window.location.href = '/index.html';
            }, 1000);
        }
        
    } catch (error) {
        console.error('Erro ao fazer logout:', error);
        window.location.href = '/index.html';
    }
}

// Função para fazer requisições à API
async function fazerRequisicao(endpoint, metodo = 'GET', dados = null) {
    try {
        const config = {
            method: metodo,
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include'
        };
        
        if (dados && (metodo === 'POST' || metodo === 'PUT')) {
            config.body = JSON.stringify(dados);
        }
        
        const response = await fetch(API_BASE_URL + endpoint, config);
        
        if (!response.ok) {
            if (response.status === 401) {
                window.location.href = '/index.html?session_expired=true';
                return null;
            }
            throw new Error(`Erro HTTP: ${response.status}`);
        }
        
        return await response.json();
        
    } catch (error) {
        console.error('Erro na requisição:', error);
        mostrarMensagem('erro', 'Erro de conexão com o servidor');
        return null;
    }
}

// Testar conexão com o servidor
async function testarConexao() {
    try {
        const data = await fazerRequisicao('/teste/conexao');
        return data && data.success;
    } catch (error) {
        return false;
    }
}

// CSS para mensagens
const mensagemCSS = `
@keyframes slideIn {
    from {
        transform: translateX(100%);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}
`;

// Adicionar CSS ao documento
(function() {
    const style = document.createElement('style');
    style.textContent = mensagemCSS;
    document.head.appendChild(style);
})();