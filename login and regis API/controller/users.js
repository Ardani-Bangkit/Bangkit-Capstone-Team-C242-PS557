
import users from "../model/user-model.js";
import bcrypt from "bcrypt";
import jwt from "jsonwebtoken";


export const Getuser = async(req,res) => {
    try {
        const Users = await users.findAll({
            attributes : ['id','fullname','email']
     } );
        res.json(Users);
    } catch (error) {
        console.error(error);
    }
}

export const regis = async(req,res) =>{
    const {fullname, email, password, confirmpw}= req.body;
    if (password !== confirmpw) return res.status(400).json({msg: "Password and Password confirmation doesn't match"});
    const salt = await bcrypt.genSalt();
    const hashpassword = await bcrypt.hash(password,salt);
    try {
        await users.create({
            fullname : fullname,
            email: email,
            password : hashpassword

        });
        res.json({msg: "Registration completed"})
    } catch (error) {
        console.log(error);
    }
}

export const login = async ( req,res) =>{
    try {
        const user = await users.findAll({
            where:{
                email: req.body.email
            }
        });
        const match = await bcrypt.compare(req.body.password, user[0].password);
        if(!match) return res.status(400).json({msg: "Wrong Password"});
        const userId = user[0].id;
        const fullname = user[0].fullname;
        const email = user[0].email;
        const acssesToken = jwt.sign({userId, fullname, email}, process.env.ACCESS_TOKEN_SECRET,{
            expiresIn: '20s'
        });
        const refreshToken = jwt.sign({userId, fullname, email}, process.env.REFRESH_TOKEN_SECRET,{
            expiresIn: '1d'
        });
        await users.update({refresh_token : refreshToken},{
            where:{
                id: userId
            }
        });
        res.cookie('refreshToken',refreshToken,{
            httponly: true,
            maxAge: 24 * 60 * 60 *1000
        });
        res.json({acssesToken});
    } catch (error) {
        res.status(404).json({msg:"Email not found"});
    }
}

export const logout = async(req , res) => {
        const refreshToken = req.cookies.refreshToken;
        if(!refreshToken) return res.sendStatus(204);
        const user = await users.findAll({
            where:{
                refresh_token : refreshToken
            }
        }
        );
    if(!user[0]) return res.sendStatus(204);
    const userId = user[0].id;
    await users.update({refresh_token : null},{
        where:{
            id: userId
        }
    });
    res.clearCookie('refreshToken');
    return res.sendStatus(200);
}

export const updateUser = async (req, res) => {
    const { id } = req.params;  // Get ID
    const { fullname, email, Gender, DateOfBirth, Adress, city, postcode, Skintype, medicalhistory, alergies, medication } = req.body;
  
    try {
      // Find User by ID
      const user = await users.findByPk(id);
      if (!user) {
        return res.status(404).json({ msg: 'User not found' });
      }
  
      // Update Data 
      await user.update({
        fullname: fullname || user.fullname,
        email: email || user.email,
        Gender: Gender || user.Gender,
        DateOfBirth: DateOfBirth || user.DateOfBirth,
        Adress: Adress || user.Adress,
        city: city || user.city,
        postcode: postcode || user.postcode,
        Skintype: Skintype || user.Skintype,
        medicalhistory: medicalhistory || user.medicalhistory,
        alergies: alergies || user.alergies,
        medication: medication || user.medication
      });
  
      res.json({ msg: 'User updated successfully' });
    } catch (error) {
      console.error(error);
      res.status(500).json({ msg: 'Error updating user data' });
    }
  };