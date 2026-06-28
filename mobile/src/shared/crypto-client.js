/**
 * crypto-client.js — End-to-end шифрование на стороне клиента (React Native)
 * Версия: 3.4 — адаптирована под expo-random + react-native-quick-crypto
 */
import * as Random from 'expo-random';
import { crypto as QuickCrypto } from 'react-native-quick-crypto';
import { Buffer } from 'buffer';

const { subtle } = QuickCrypto;

class DarkCrypto {
  // =========================================================================
  // 1. ГЕНЕРАЦИЯ МНЕМОНИКИ (BIP39)
  // =========================================================================
  static async generateMnemonic() {
    const wordlist = [
      "abandon","ability","able","about","above","absent","absorb","abstract","absurd","abuse",
      "access","accident","account","accuse","achieve","acid","acoustic","acquire","across","act",
      "action","actor","actress","actual","adapt","add","addict","address","adjust","admit",
      "adult","advance","advice","aerobic","affair","afford","afraid","again","age","agent",
      "agree","ahead","aim","air","airport","aisle","alarm","album","alcohol","alert","alien",
      "all","alley","allow","almost","alone","alpha","already","also","alter","always",
      "amateur","amazing","among","amount","amused","analyst","anchor","ancient","anger",
      "angle","angry","animal","ankle","announce","annual","another","answer","antenna",
      "antique","anxiety","any","apart","apology","appear","apple","approve","april","arch",
      "arctic","area","arena","argue","arm","armed","armor","army","around","arrange",
      "arrest","arrive","arrow","art","artefact","artist","artwork","ask","aspect","assault",
      "asset","assist","assume","asthma","athlete","atom","attack","attend","attitude","attract",
      "auction","audit","august","aunt","author","auto","autumn","average","avocado","avoid",
      "awake","aware","away","awesome","awful","awkward","axis","baby","bachelor","bacon",
      "badge","bag","balance","balcony","ball","bamboo","banana","banner","bar","barely",
      "bargain","barrel","base","basic","basket","battle","beach","bean","beauty","become",
      "beef","before","begin","behave","behind","believe","below","belt","bench","benefit",
      "best","betray","better","between","beyond","bicycle","bid","bike","bind","biology",
      "bird","birth","bitter","black","blade","blame","blanket","blast","bleak","bless",
      "blind","blood","blossom","blouse","blue","blur","blush","board","boat","body",
      "boil","bomb","bone","bonus","book","boost","border","boring","borrow","boss",
      "bottom","bounce","box","boy","bracket","brain","brand","brass","brave","bread",
      "breeze","brick","bridge","brief","bright","bring","brisk","broccoli","broken","bronze",
      "broom","brother","brown","brush","bubble","buddy","budget","buffalo","build","bulb",
      "bulk","bullet","bundle","bunker","burden","burger","burst","bus","business","busy",
      "butter","buyer","buzz","cabbage","cabin","cable","cactus","cage","cake","call",
      "calm","camera","camp","can","canal","cancel","candy","cannon","canoe","canvas",
      "canyon","capable","capital","captain","car","carbon","card","cargo","carpet","carry",
      "cart","case","cash","casino","castle","casual","cat","catalog","catch","category",
      "cattle","caught","cause","caution","cave","ceiling","celery","cement","census","century",
      "cereal","certain","chair","chalk","champion","change","chaos","chapter","charge","chase",
      "chat","cheap","check","cheese","chef","cherry","chest","chicken","chief","child",
      "chimney","choice","choose","chronic","chuckle","chunk","churn","cigar","cinnamon","circle",
      "citizen","city","civil","claim","clap","clarify","claw","clay","clean","clerk",
      "clever","click","client","cliff","climb","clinic","clip","clock","clog","close",
      "cloth","cloud","clown","club","clump","cluster","clutch","coach","coast","coconut",
      "code","coffee","coil","coin","collect","color","column","combine","come","comfort",
      "comic","common","company","concert","conduct","confirm","congress","connect","consider",
      "control","convince","cook","cool","copper","copy","coral","core","corn","correct",
      "cost","cotton","couch","country","couple","course","cousin","cover","coyote","crack",
      "cradle","craft","cram","crane","crash","crater","crawl","crazy","cream","credit",
      "creek","crew","cricket","crime","crisp","critic","crop","cross","crouch","crowd",
      "crucial","cruel","cruise","crumble","crunch","crush","cry","crystal","cube","culture",
      "cup","cupboard","curious","current","curtain","curve","cushion","custom","cute","cycle",
      "dad","damage","damp","dance","danger","daring","dash","daughter","dawn","day",
      "deal","debate","debris","decade","december","decide","decline","decorate","decrease",
      "deer","defense","define","defy","degree","delay","deliver","demand","demise","denial",
      "dentist","deny","depart","depend","deposit","depth","deputy","derive","describe",
      "desert","design","desk","despair","destroy","detail","detect","develop","device",
      "devote","diagram","dial","diamond","diary","dice","diesel","diet","differ","digital",
      "dignity","dilemma","dinner","dinosaur","direct","dirt","disagree","discover","disease",
      "dish","dismiss","disorder","display","distance","divert","divide","divorce","dizzy",
      "doctor","document","dog","doll","dolphin","domain","donate","donkey","donor","door",
      "dose","double","dove","draft","dragon","drama","drastic","draw","dream","dress",
      "drift","drill","drink","drip","drive","drop","drum","dry","duck","dumb",
      "dune","during","dust","dutch","duty","dwarf","dynamic","eager","eagle","early",
      "earn","earth","easily","east","easy","echo","ecology","economy","edge","edit",
      "educate","effort","egg","eight","either","elbow","elder","electric","elegant","element",
      "elephant","elevator","elite","else","embark","embody","embrace","emerge","emotion",
      "employ","empower","empty","enable","enact","end","endless","endorse","enemy",
      "energy","enforce","engage","engine","enhance","enjoy","enlist","enough","enrich",
      "enroll","ensure","enter","entire","entry","envelope","episode","equal","equip","era",
      "erase","erode","erosion","error","erupt","escape","essay","essence","estate","eternal",
      "ethics","evidence","evil","evoke","evolve","exact","example","excess","exchange",
      "excite","exclude","excuse","execute","exercise","exhaust","exhibit","exile","exist",
      "exit","exotic","expand","expect","expire","explain","expose","express","extend","extra",
      "eye","eyebrow","fabric","face","faculty","fade","faint","faith","fall","false",
      "fame","family","famous","fan","fancy","fantasy","farm","fashion","fat","fatal",
      "father","fatigue","fault","favorite","feature","february","federal","fee","feed",
      "feel","female","fence","festival","fetch","fever","few","fiber","fiction","field",
      "figure","file","film","filter","final","find","fine","finger","finish","fire",
      "firm","first","fiscal","fish","fit","fitness","fix","flag","flame","flash",
      "flat","flavor","flee","flight","flip","float","flock","floor","flower","fluid",
      "flush","fly","foam","focus","fog","foil","fold","follow","food","foot",
      "force","forest","forget","fork","fortune","forum","forward","fossil","foster","found",
      "fox","fragile","frame","frequent","fresh","friend","fringe","frog","front","frost",
      "frown","frozen","fruit","fuel","fun","funny","furnace","fury","future","gadget",
      "gain","galaxy","gallery","game","gap","garage","garbage","garden","garlic","garment",
      "gas","gasp","gate","gather","gauge","gaze","general","genius","genre","gentle",
      "genuine","gesture","ghost","giant","gift","giggle","ginger","giraffe","girl","give",
      "glad","glance","glare","glass","glide","glimpse","globe","gloom","glory","glove",
      "glow","glue","goat","goddess","gold","good","goose","gorilla","gospel","gossip",
      "govern","gown","grab","grace","grain","grant","grape","grass","gravity","great",
      "green","grid","grief","grit","grocery","group","grow","grunt","guard","guess",
      "guide","guilt","guitar","gun","gym","habit","hair","half","hammer","hamster",
      "hand","happy","harbor","hard","harsh","harvest","hat","have","hawk","hazard",
      "head","health","heart","heavy","hedgehog","height","hello","helmet","help","hen",
      "hero","hidden","high","hill","hint","hip","hire","history","hobby","hockey",
      "hold","hole","holiday","hollow","home","honey","hood","hope","horn","horror",
      "horse","hospital","host","hotel","hour","hover","hub","huge","human","humble",
      "humor","hundred","hungry","hunt","hurdle","hurry","hurt","husband","hybrid","ice",
      "icon","idea","identify","idle","ignore","ill","illegal","illness","image","imitate",
      "immense","immune","impact","impose","improve","impulse","inch","include","income",
      "increase","index","indicate","indoor","industry","infant","inflict","inform","inhale",
      "inherit","initial","inject","injury","inmate","inner","innocent","input","inquiry",
      "insane","insect","inside","inspire","install","intact","interest","into","invest",
      "invite","involve","iron","island","isolate","issue","item","ivory","jacket","jaguar",
      "jar","jazz","jealous","jeans","jelly","jewel","job","join","joke","journey",
      "joy","judge","juice","jump","jungle","junior","junk","just","kangaroo","keen",
      "keep","ketchup","key","kick","kid","kidney","kind","kingdom","kiss","kit",
      "kitchen","kite","kitten","kiwi","knee","knife","knock","know","lab","label",
      "labor","ladder","lady","lake","lamp","language","laptop","large","later","laugh",
      "laundry","lava","law","lawn","lawsuit","layer","lazy","leader","leaf","learn",
      "leave","lecture","left","leg","legal","legend","leisure","lemon","lend","length",
      "lens","leopard","lesson","letter","level","liar","liberty","library","license","life",
      "lift","light","like","limb","limit","link","lion","liquid","list","little",
      "live","lizard","load","loan","lobster","local","lock","logic","lonely","long",
      "loop","lottery","loud","lounge","love","loyal","lucky","luggage","lumber","lunar",
      "lunch","luxury","lyrics","machine","mad","magic","magnet","maid","mail","main",
      "major","make","mammal","man","manage","mandate","mango","mansion","manual","maple",
      "marble","march","margin","marine","market","marriage","mask","mass","master","match",
      "material","math","matrix","matter","maximum","maze","meadow","mean","measure","meat",
      "mechanic","medal","media","melody","melt","member","memory","mention","menu","mercy",
      "merge","merit","merry","mesh","message","metal","method","middle","midnight","milk",
      "million","mimic","mind","minimum","minor","minute","miracle","mirror","misery","miss",
      "mistake","mix","mixed","mixture","mobile","model","modify","mom","moment","monitor",
      "monkey","monster","month","moon","moral","more","morning","mosquito","mother","motion",
      "motor","mountain","mouse","move","movie","much","muffin","mule","multiply","muscle",
      "museum","mushroom","music","must","mutual","myself","mystery","myth","naive","name",
      "napkin","narrow","nasty","nation","nature","near","neck","need","negative","neglect",
      "neither","nephew","nerve","nest","net","network","neutral","never","news","next",
      "nice","night","noble","noise","nominee","noodle","normal","north","nose","notable",
      "note","nothing","notice","novel","now","nuclear","number","nurse","nut","oak",
      "obey","object","oblige","obscure","observe","obtain","obvious","occur","ocean","october",
      "odor","off","offer","office","often","oil","okay","old","olive","olympic",
      "omit","once","one","onion","online","only","open","opera","opinion","oppose",
      "option","orange","orbit","orchard","order","ordinary","organ","orient","original",
      "orphan","ostrich","other","outdoor","outer","output","outside","oval","oven","over",
      "own","owner","oxygen","oyster","ozone","pact","paddle","page","pair","palace",
      "palm","panda","panel","panic","panther","paper","parade","parent","park","parrot",
      "party","pass","patch","path","patient","patrol","pattern","pause","pave","payment",
      "peace","peanut","pear","peasant","pelican","pen","penalty","pencil","people","pepper",
      "perfect","permit","person","pet","phone","photo","phrase","physical","piano","picnic",
      "picture","piece","pig","pigeon","pill","pilot","pink","pioneer","pipe","pistol",
      "pitch","pizza","place","planet","plastic","plate","play","please","pledge","pluck",
      "plug","plunge","poem","poet","point","polar","pole","police","pond","pony",
      "pool","popular","portion","position","possible","post","potato","pottery","poverty",
      "powder","power","practice","praise","predict","prefer","prepare","present","pretty",
      "prevent","price","pride","primary","print","priority","prison","private","prize",
      "problem","process","produce","profit","program","project","promote","proof","property",
      "prosper","protect","proud","provide","public","pudding","pull","pulp","pulse","pumpkin",
      "punch","pupil","puppy","purchase","purity","purpose","purse","push","put","puzzle",
      "pyramid","quality","quantum","quarter","question","quick","quit","quiz","quote","rabbit",
      "raccoon","race","rack","radar","radio","rail","rain","raise","rally","ramp",
      "ranch","random","range","rapid","rare","rate","rather","raven","raw","razor",
      "ready","real","reason","rebel","rebuild","recall","receive","recipe","record","recycle",
      "reduce","reflect","reform","refuse","region","regret","regular","reject","relax","release",
      "relief","rely","remain","remember","remind","remove","render","renew","rent","reopen",
      "repair","repeat","replace","report","require","rescue","resemble","resist","resource",
      "response","result","retire","retreat","return","reunion","reveal","review","reward",
      "rhythm","rib","ribbon","rice","rich","ride","ridge","rifle","right","rigid",
      "ring","riot","ripple","risk","ritual","rival","river","road","roast","robot",
      "robust","rocket","romance","roof","rookie","room","rose","rotate","rough","round",
      "route","royal","rubber","rude","rug","rule","run","runway","rural","sad",
      "saddle","sadness","safe","sail","salad","salmon","salon","salt","salute","same",
      "sample","sand","satisfy","satoshi","sauce","sausage","save","say","scale","scan",
      "scare","scatter","scene","scheme","school","science","scissors","scorpion","scout","scrap",
      "screen","script","scrub","sea","search","season","seat","second","secret","section",
      "security","seed","seek","segment","select","sell","seminar","senior","sense","sentence",
      "series","service","session","settle","setup","seven","shadow","shaft","shallow","share",
      "shed","shell","sheriff","shield","shift","shine","ship","shiver","shock","shoe",
      "shoot","shop","short","shoulder","shove","shrimp","shrug","shuffle","shy","sibling",
      "sick","side","siege","sight","sign","silent","silk","silly","silver","similar",
      "simple","since","sing","siren","sister","situate","six","size","skate","sketch",
      "ski","skill","skin","skirt","skull","slab","slam","sleep","slender","slice",
      "slide","slight","slim","slogan","slot","slow","slush","small","smart","smile",
      "smoke","smooth","snack","snake","snap","sniff","snow","soap","soccer","social",
      "sock","soda","soft","solar","soldier","solid","solution","solve","someone","song",
      "soon","sorry","sort","soul","sound","soup","source","south","space","spare",
      "spatial","spawn","speak","special","speed","spell","spend","sphere","spice","spider",
      "spike","spin","spirit","split","spoil","sponsor","spoon","sport","spot","spray",
      "spread","spring","spy","square","squeeze","squirrel","stable","stadium","staff","stage",
      "stairs","stamp","stand","start","state","stay","steak","steel","stem","step",
      "stereo","stick","still","sting","stock","stomach","stone","stool","story","stove",
      "strategy","street","strike","strong","struggle","student","stuff","stumble","style","subject",
      "submit","subway","success","such","sudden","suffer","sugar","suggest","suit","summer",
      "sun","sunny","sunset","super","supply","supreme","sure","surface","surge","surprise",
      "surround","survey","suspect","sustain","swallow","swamp","swap","swarm","swear","sweet",
      "swift","swim","swing","switch","sword","symbol","symptom","syrup","system","table",
      "tackle","tag","tail","talent","talk","tank","tape","target","task","taste",
      "tattoo","taxi","teach","team","tell","ten","tenant","tennis","tent","term",
      "test","text","thank","that","theme","then","theory","there","they","thing",
      "this","thought","three","thrive","throw","thumb","thunder","ticket","tide","tiger",
      "tilt","timber","time","tiny","tip","tired","tissue","title","toast","tobacco",
      "today","toddler","toe","together","toilet","token","tomato","tomorrow","tone","tongue",
      "tonight","tool","tooth","top","topic","topple","torch","tornado","tortoise","toss",
      "total","tourist","toward","tower","town","toy","track","trade","traffic","tragic",
      "train","transfer","trap","trash","travel","tray","treat","tree","trend","trial",
      "tribe","trick","trigger","trim","trip","trophy","trouble","truck","true","truly",
      "trumpet","trust","truth","try","tube","tuition","tumble","tuna","tunnel","turkey",
      "turn","turtle","twelve","twenty","twice","twin","twist","two","type","typical",
      "ugly","umbrella","unable","unaware","uncle","uncover","under","undo","unfair","unfold",
      "unhappy","uniform","unique","unit","universe","unknown","unlock","until","unusual","unveil",
      "update","upgrade","uphold","upon","upper","upset","urban","urge","usage","use",
      "used","useful","useless","usual","utility","vacant","vacuum","vague","valid","valley",
      "valve","van","vanish","vapor","various","vast","vault","vehicle","velvet","vendor",
      "venture","venue","verb","verify","version","very","vessel","veteran","viable","vibrant",
      "vicious","victory","video","view","village","vintage","violin","virtual","virus","visa",
      "visit","visual","vital","vivid","vocal","voice","void","volcano","volume","vote",
      "voyage","wage","wagon","wait","walk","wall","walnut","want","warfare","warm",
      "warrior","wash","wasp","waste","water","wave","way","wealth","weapon","wear",
      "weasel","weather","web","wedding","weekend","weird","welcome","west","wet","whale",
      "what","wheat","wheel","when","where","whip","whisper","wide","width","wife",
      "wild","will","win","window","wine","wing","wink","winner","winter","wire",
      "wisdom","wise","wish","witness","wolf","woman","wonder","wood","wool","word",
      "work","world","worry","worth","wrap","wreck","wrestle","wrist","write","wrong",
      "yard","year","yellow","you","young","youth","zebra","zero","zone","zoo"
    ];

    const entropy = Random.getRandomBytes(32);
    const hash = await subtle.digest('SHA-256', entropy);
    const checksumBits = 8;
    const checksumByte = new Uint8Array(hash)[0];
    const checksum = checksumByte >> (8 - checksumBits);
    const fullBits = [];
    for (let i = 0; i < entropy.length; i++) {
      for (let b = 7; b >= 0; b--) {
        fullBits.push((entropy[i] >> b) & 1);
      }
    }
    for (let b = checksumBits - 1; b >= 0; b--) {
      fullBits.push((checksum >> b) & 1);
    }
    const words = [];
    for (let i = 0; i < 24; i++) {
      let index = 0;
      for (let j = 0; j < 11; j++) {
        index = (index << 1) | fullBits[i * 11 + j];
      }
      words.push(wordlist[index]);
    }
    return words.join(' ');
  }

  // =========================================================================
  // 2. ДЕРИВАЦИЯ КЛЮЧЕЙ ИЗ МНЕМОНИКИ
  // =========================================================================
  static async deriveKeyPair(mnemonic) {
    const seed = await this._mnemonicToSeed(mnemonic);
    const rawPrivate = new Uint8Array(seed.slice(0, 32));
    const d = this._normalizePrivateKey(rawPrivate);
    const point = this._derivePubPoint(d);

    const jwkSign = {
      kty: 'EC', crv: 'P-256',
      d: this._bytesToBase64Url(d),
      x: this._bytesToBase64Url(point.x),
      y: this._bytesToBase64Url(point.y),
      ext: true,
    };
    const signPrivateKey = await subtle.importKey(
      'jwk', jwkSign, { name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign']
    );
    const ecdhPrivateKey = await subtle.importKey(
      'jwk', jwkSign, { name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']
    );
    const jwk = await subtle.exportKey('jwk', signPrivateKey);
    const xBytes = this._base64UrlToBytes(jwk.x);
    const yBytes = this._base64UrlToBytes(jwk.y);
    const prefix = (yBytes[31] % 2 === 0) ? 0x02 : 0x03;
    const compressed = new Uint8Array(33);
    compressed[0] = prefix;
    compressed.set(xBytes, 1);
    const hash = await subtle.digest('SHA-256', compressed);
    const address = Array.from(new Uint8Array(hash))
      .map(b => b.toString(16).padStart(2, '0')).join('');
    return { signPrivateKey, ecdhPrivateKey, compressedPubKey: compressed, address };
  }

  // =========================================================================
  // 3. ДЕКОМПРЕССИЯ ПУБЛИЧНОГО КЛЮЧА
  // =========================================================================
  static decompressPublicKey(compressedKey) {
    if (compressedKey.length !== 33 || (compressedKey[0] !== 0x02 && compressedKey[0] !== 0x03)) {
      throw new Error('Invalid compressed key');
    }
    const p = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFFn;
    const a = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFCn;
    const b = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604Bn;
    const x = BigInt('0x' + Array.from(compressedKey.slice(1)).map(b => b.toString(16).padStart(2,'0')).join(''));
    const rhs = (x * x * x + a * x + b) % p;

    const modPow = (base, exp) => {
      let res = 1n;
      while (exp > 0n) {
        if (exp & 1n) res = (res * base) % p;
        base = (base * base) % p;
        exp >>= 1n;
      }
      return res;
    };

    let y = modPow(rhs, (p + 1n) / 4n);
    if ((y & 1n) !== (compressedKey[0] === 0x03 ? 1n : 0n)) {
      y = p - y;
    }
    const xBytes = this._to32Bytes(x);
    const yBytes = this._to32Bytes(y);
    const uncompressed = new Uint8Array(65);
    uncompressed[0] = 0x04;
    uncompressed.set(xBytes, 1);
    uncompressed.set(yBytes, 33);
    return uncompressed;
  }

  // =========================================================================
  // 4. ECDH ОБЩИЙ СЕКРЕТ
  // =========================================================================
  static async getSharedSecret(myEcdhPrivateKey, theirPubKeyBytes) {
    let pubKey = theirPubKeyBytes;
    if (pubKey.length === 33 && (pubKey[0] === 0x02 || pubKey[0] === 0x03)) {
      pubKey = this.decompressPublicKey(pubKey);
    }
    const pubKeyObj = await subtle.importKey(
      'raw', pubKey, { name: 'ECDH', namedCurve: 'P-256' }, false, []
    );
    const shared = await subtle.deriveBits(
      { name: 'ECDH', public: pubKeyObj }, myEcdhPrivateKey, 256
    );
    return shared;
  }

  // =========================================================================
  // 5. AES-GCM ШИФРОВАНИЕ / ДЕШИФРОВАНИЕ
  // =========================================================================
  static async encryptAES(sharedSecret, plaintext) {
    const iv = Random.getRandomBytes(12);
    const key = await subtle.importKey(
      'raw', sharedSecret, { name: 'AES-GCM' }, false, ['encrypt']
    );
    const encoded = new TextEncoder().encode(plaintext);
    const ciphertext = await subtle.encrypt(
      { name: 'AES-GCM', iv }, key, encoded
    );
    return { ciphertext, iv };
  }

  static async decryptAES(sharedSecret, ciphertext, iv) {
    const key = await subtle.importKey(
      'raw', sharedSecret, { name: 'AES-GCM' }, false, ['decrypt']
    );
    const decrypted = await subtle.decrypt(
      { name: 'AES-GCM', iv }, key, ciphertext
    );
    return new TextDecoder().decode(decrypted);
  }

  // =========================================================================
  // 6. ШИФРОВАНИЕ / ДЕШИФРОВАНИЕ СООБЩЕНИЙ (обёртки)
  // =========================================================================
  static async encryptMessage(myEcdhPrivateKey, myCompressedPubKey, recipientPubKey, plaintext) {
    const shared = await this.getSharedSecret(myEcdhPrivateKey, recipientPubKey);
    const { ciphertext, iv } = await this.encryptAES(shared, plaintext);
    return {
      ciphertext: this._arrayBufferToBase64(ciphertext),
      iv: this._toBase64(iv),
      myPubKey: this._toBase64(myCompressedPubKey)
    };
  }

  static async decryptMessage(myEcdhPrivateKey, senderCompressedPubKey, ivBase64, ciphertextBase64) {
    const iv = this._fromBase64(ivBase64);
    const ciphertext = this._base64ToArrayBuffer(ciphertextBase64);
    const shared = await this.getSharedSecret(myEcdhPrivateKey, senderCompressedPubKey);
    return await this.decryptAES(shared, ciphertext, iv);
  }

  // =========================================================================
  // 7. ПОДПИСЬ ДАННЫХ
  // =========================================================================
  static async signData(privateKey, dataString) {
    const signature = await subtle.sign(
      { name: 'ECDSA', hash: 'SHA-256' },
      privateKey,
      new TextEncoder().encode(dataString)
    );
    return new Uint8Array(signature);
  }

  // =========================================================================
  // 8. ВЕРИФИКАЦИЯ ПОДПИСИ
  // =========================================================================
  static async verifySignature(publicKeyBytes, signature, dataString) {
    const pubKeyObj = await subtle.importKey(
      'raw', publicKeyBytes, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']
    );
    return await subtle.verify(
      { name: 'ECDSA', hash: 'SHA-256' },
      pubKeyObj,
      signature,
      new TextEncoder().encode(dataString)
    );
  }

  // =========================================================================
  // 9. ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ (исправлены с использованием Buffer)
  // =========================================================================
  static async _mnemonicToSeed(mnemonic) {
    const keyMaterial = await subtle.importKey(
      'raw', new TextEncoder().encode(mnemonic),
      'PBKDF2', false, ['deriveBits']
    );
    return subtle.deriveBits(
      { name: 'PBKDF2', salt: new TextEncoder().encode('mnemonic'),
        iterations: 2048, hash: 'SHA-512' },
      keyMaterial, 512
    );
  }

  static _normalizePrivateKey(rawBytes) {
    const n = BigInt("0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551");
    let scalar = 0n;
    for (let i = 0; i < rawBytes.length; i++) {
      scalar = (scalar << 8n) | BigInt(rawBytes[i]);
    }
    scalar = (scalar % (n - 1n)) + 1n;
    const hex = scalar.toString(16).padStart(64, '0');
    const bytes = new Uint8Array(32);
    for (let i = 0; i < 32; i++) {
      bytes[i] = parseInt(hex.substring(i * 2, i * 2 + 2), 16);
    }
    return bytes;
  }

  static _derivePubPoint(privateScalar) {
    const p = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFFn;
    const a = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFCn;
    const Gx = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296n;
    const Gy = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5n;
    const n = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551n;

    let d = 0n;
    for (let i = 0; i < privateScalar.length; i++) {
      d = (d << 8n) | BigInt(privateScalar[i]);
    }
    d = d % n;
    if (d === 0n) {
      return { x: this._to32Bytes(Gx), y: this._to32Bytes(Gy) };
    }

    const mod = (x) => {
      let r = x % p;
      return r < 0n ? r + p : r;
    };
    const modAdd = (x, y) => mod((x + y) % p);
    const modSub = (x, y) => mod((x - y + p) % p);
    const modMul = (x, y) => mod((x * y) % p);

    const modInv = (x) => {
      if (x === 0n) throw new Error('Division by zero');
      let a = mod(x), prevA = 1n;
      let b = p, prevB = 0n;
      while (b !== 0n) {
        const q = a / b;
        [a, b] = [b, a - q * b];
        [prevA, prevB] = [prevB, prevA - q * prevB];
      }
      return mod(prevA);
    };

    const modDiv = (x, y) => modMul(x, modInv(y));

    const double = (P) => {
      if (P === null) return null;
      const [x, y] = [P.x, P.y];
      if (y === 0n) return null;
      const s = modDiv(modAdd(modMul(3n, modMul(x, x)), a), modMul(2n, y));
      const x2 = modSub(modMul(s, s), modMul(2n, x));
      const y2 = modSub(modMul(s, modSub(x, x2)), y);
      return { x: x2, y: y2 };
    };

    const add = (P, Q) => {
      if (P === null) return Q;
      if (Q === null) return P;
      if (P.x === Q.x) {
        if (P.y !== Q.y) return null;
        return double(P);
      }
      const s = modDiv(modSub(Q.y, P.y), modSub(Q.x, P.x));
      const x3 = modSub(modMul(s, s), modAdd(P.x, Q.x));
      const y3 = modSub(modMul(s, modSub(P.x, x3)), P.y);
      return { x: x3, y: y3 };
    };

    let Q = null;
    let R = { x: Gx, y: Gy };
    while (d > 0n) {
      if (d & 1n) {
        Q = add(Q, R);
      }
      R = double(R);
      d >>= 1n;
    }
    return { x: this._to32Bytes(Q.x), y: this._to32Bytes(Q.y) };
  }

  static _to32Bytes(value) {
    const hex = value.toString(16).padStart(64, '0');
    const bytes = new Uint8Array(32);
    for (let i = 0; i < 32; i++) {
      bytes[i] = parseInt(hex.substring(i * 2, i * 2 + 2), 16);
    }
    return bytes;
  }

  // === ИСПРАВЛЕННЫЕ МЕТОДЫ (без btoa/atob) ===
  static _toBase64(arr) {
    return Buffer.from(arr).toString('base64');
  }

  static _fromBase64(str) {
    return new Uint8Array(Buffer.from(str, 'base64'));
  }

  static _arrayBufferToBase64(buffer) {
    return Buffer.from(buffer).toString('base64');
  }

  static _base64ToArrayBuffer(base64) {
    const buffer = Buffer.from(base64, 'base64');
    return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
  }

  static _bytesToBase64Url(bytes) {
    return Buffer.from(bytes).toString('base64')
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
  }

  static _base64UrlToBytes(base64url) {
    const base64 = base64url.replace(/-/g, '+').replace(/_/g, '/');
    return new Uint8Array(Buffer.from(base64, 'base64'));
  }

  static _concat(a, b) {
    const c = new Uint8Array(a.length + b.length);
    c.set(a, 0);
    c.set(b, a.length);
    return c;
  }

  // =========================================================================
  // 10. ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ ДЛЯ РАБОТЫ С ФАЙЛАМИ
  // =========================================================================
  static async encryptFile(fileData, key, iv) {
    const cryptoKey = await subtle.importKey('raw', key, { name: 'AES-GCM' }, false, ['encrypt']);
    const encrypted = await subtle.encrypt({ name: 'AES-GCM', iv }, cryptoKey, fileData);
    return new Uint8Array(encrypted);
  }

  static async decryptFile(encryptedData, key, iv) {
    const cryptoKey = await subtle.importKey('raw', key, { name: 'AES-GCM' }, false, ['decrypt']);
    const decrypted = await subtle.decrypt({ name: 'AES-GCM', iv }, cryptoKey, encryptedData);
    return decrypted;
  }

  static generateFileKeyAndIv() {
    const key = Random.getRandomBytes(32);
    const iv = Random.getRandomBytes(12);
    return { key, iv };
  }

  static arrayBufferToBase64(buffer) {
    return Buffer.from(buffer).toString('base64');
  }

  static base64ToArrayBuffer(base64) {
    const buffer = Buffer.from(base64, 'base64');
    return buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength);
  }
}

export default DarkCrypto;