window.__installOverlay = ({ w, h }) => {
	// --- canvas overlay (re-created on every share) ---
	let c = document.getElementById("__scOverlay");
	if (!c) {
		c = document.createElement("canvas");
		c.id = "__scOverlay";
		document.body.appendChild(c);
	}
	c.width = w;
	c.height = h;
	c.style.cssText = [
		"position:fixed",
		"inset:0",
		"width:100vw",
		"height:100vh",
		"z-index:999999",
		"pointer-events:none",
	].join(";");
	const ctx = c.getContext("2d");
	ctx.fillStyle = "#1a1a2e";
	ctx.fillRect(0, 0, w, h);

	let _lastImg = null;
	const _repaint = () => {
		if (_lastImg) ctx.drawImage(_lastImg, 0, 0, w, h);
	};
	if (window.__canvasRepaintId) clearInterval(window.__canvasRepaintId);
	window.__canvasRepaintId = setInterval(_repaint, 66);
	window.__pushFrame = (b64) => {
		const img = new Image();
		img.onload = () => {
			_lastImg = img;
			ctx.drawImage(img, 0, 0, w, h);
		};
		img.src = "data:image/jpeg;base64," + b64;
	};

	// --- getDisplayMedia override (installed once) ---
	if (!window.__scOrigGDM) {
		const md = navigator.mediaDevices;
		window.__scOrigGDM = md.getDisplayMedia.bind(md);
		md.getDisplayMedia = async (constraints) => {
			constraints = constraints || {};
			constraints.audio = false;
			constraints.selfBrowserSurface = "include";
			constraints.video = { displaySurface: "browser" };
			try {
				const s = await window.__scOrigGDM(constraints);
				window.__scShareOk = true;
				return s;
			} catch (e) {
				window.__scShareOk = false;
				throw e;
			}
		};
	}
};

window.__removeOverlay = () => {
	const el = document.getElementById("__scOverlay");
	if (el) el.remove();
	window.__pushFrame = null;
	window.__scShareOk = null;
	if (window.__canvasRepaintId) {
		clearInterval(window.__canvasRepaintId);
		window.__canvasRepaintId = null;
	}
};
